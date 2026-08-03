#!/usr/bin/env python
"""Portable local UI for IPS/HSD -> Copilot CLI workflows.

The app intentionally uses only the Python standard library so the hardware flow kit
can be copied to another Windows PC without installing web UI dependencies.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import html
import json
import os
import pathlib
import queue
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


KIT_ROOT = pathlib.Path(__file__).resolve().parents[1]

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
AUTO_REPORTS_DIR = KIT_ROOT / "out" / "auto_reports"
ACTIVE_TASK_STATUSES = ("queued", "running", "waiting_resource", "cancelling")
TERMINAL_TASK_STATUSES = ("completed", "failed", "cancelled", "interrupted")


def load_config(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    cfg["_config_path"] = str(path)
    return cfg


def load_machine_options(cfg: dict[str, Any]) -> list[dict[str, str]]:
    matching_cfg = cfg.get("machineMatching", {})
    inventory_path = pathlib.Path(
        matching_cfg.get("inventoryPath", "config/lab-machine-inventory.json")
    )
    if not inventory_path.is_absolute():
        inventory_path = KIT_ROOT / inventory_path
    with inventory_path.open("r", encoding="utf-8-sig") as f:
        inventory = json.load(f)

    options: list[dict[str, str]] = []
    for machine in inventory.get("machines", []):
        machine_id = safe_text(machine.get("id"))
        family = safe_text(machine.get("platformFamily"))
        user = safe_text(machine.get("ssh", {}).get("user"))
        host = safe_text(machine.get("ssh", {}).get("host"))
        if not all((machine_id, family, user, host)):
            raise ValueError(f"Invalid machine inventory entry: {machine!r}")
        options.append(
            {
                "value": f"{user}@{host}",
                "label": f"{machine_id} ({family}) - {user}@{host}",
            }
        )
    if not options:
        raise ValueError(f"No machines found in inventory: {inventory_path}")
    return options


def deep_set(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    node = cfg
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def require_numeric_id(value: str, field_name: str) -> str:
    if not value.isdigit():
        raise ValueError(f"{field_name} must contain digits only")
    return value


def auto_query_dir(query_id: str) -> pathlib.Path:
    return AUTO_REPORTS_DIR / f"query_{require_numeric_id(query_id, 'query_id')}"


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def safe_report_path(path_text: str) -> str:
    path = pathlib.Path(path_text)
    if path.is_absolute():
        raise ValueError("report_path must be relative to the kit root")
    resolved = (KIT_ROOT / path).resolve()
    out_root = (KIT_ROOT / "out").resolve()
    if resolved != out_root and out_root not in resolved.parents:
        raise ValueError("report_path must be under out")
    return str(resolved.relative_to(KIT_ROOT))


def report_url(report_base_url: str, path: str) -> str:
    base = report_base_url.rstrip("/")
    return f"{base}{path}" if base else ""


class TaskStore:
    """SQLite-backed shared state for automatic Query tasks and machine reservations."""

    def __init__(self, path: pathlib.Path, per_machine_concurrency: dict[str, Any] | None = None, recover_active: bool = True) -> None:
        self.path = path
        self.per_machine_concurrency = per_machine_concurrency or {"default": 1}
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize(recover_active)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self, recover_active: bool) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS query_tasks (
                    id TEXT PRIMARY KEY,
                    query_id TEXT NOT NULL,
                    creator_name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    status TEXT NOT NULL,
                    current_ips_id TEXT NOT NULL DEFAULT '',
                    current_round INTEGER NOT NULL DEFAULT 0,
                    interval_seconds INTEGER NOT NULL,
                    manager_recipients TEXT NOT NULL DEFAULT '',
                    report_base_url TEXT NOT NULL DEFAULT '',
                    output TEXT NOT NULL DEFAULT '',
                    cancellation_reason TEXT NOT NULL DEFAULT '',
                    processed_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    process_id INTEGER,
                    report_path TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS machine_locks (
                    machine_key TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    PRIMARY KEY (machine_key, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_query_tasks_status ON query_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_machine_locks_machine ON machine_locks(machine_key);
            """)
            if recover_active:
                now = time.time()
                conn.execute(
                    "UPDATE query_tasks SET status='interrupted', completed_at=?, updated_at=?, "
                    "cancellation_reason=CASE WHEN cancellation_reason='' THEN ? ELSE cancellation_reason END "
                    "WHERE status IN ('queued','running','waiting_resource','cancelling')",
                    (now, now, "UI service restarted; automatic processing was not resumed."),
                )

    @staticmethod
    def _task(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        task = dict(row)
        try:
            task["processed"] = json.loads(task.pop("processed_json"))
        except (TypeError, json.JSONDecodeError):
            task["processed"] = {}
        return task

    def create_task(self, query_id: str, creator_name: str, interval_minutes: int, manager_recipients: str, report_base_url: str) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO query_tasks (id,query_id,creator_name,created_at,updated_at,status,interval_seconds,manager_recipients,report_base_url) "
                "VALUES (?,?,?,?,?,'queued',?,?,?)",
                (task_id, query_id, creator_name, now, now, interval_minutes * 60, manager_recipients, report_base_url),
            )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as conn:
            return self._task(conn.execute("SELECT * FROM query_tasks WHERE id=?", (task_id,)).fetchone())

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM query_tasks ORDER BY created_at DESC").fetchall()
            return [self._task(row) for row in rows if row is not None]

    def update(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "started_at", "completed_at", "current_ips_id", "current_round", "manager_recipients", "report_base_url", "cancellation_reason", "processed_json", "error_text", "process_id", "report_path"}
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return self.get_task(task_id) or {}
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(f"UPDATE query_tasks SET {assignments} WHERE id=?", (*values.values(), task_id))
        return self.get_task(task_id) or {}

    def append_output(self, task_id: str, text: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE query_tasks SET output=substr(output || ?, -200000), updated_at=? WHERE id=?",
                (f"[{timestamp}] {text.rstrip()}\n", time.time(), task_id),
            )

    def request_cancel(self, task_id: str, reason: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError("task not found")
        if task["status"] in TERMINAL_TASK_STATUSES:
            return task
        if task["status"] == "queued":
            return self.update(task_id, status="cancelled", completed_at=time.time(), cancellation_reason=reason, current_ips_id="")
        return self.update(task_id, status="cancelling", cancellation_reason=reason)

    def machine_limit(self, machine_key: str) -> int:
        value = self.per_machine_concurrency.get(machine_key, self.per_machine_concurrency.get("default", 1))
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def try_acquire_machine(self, task_id: str, machine_key: str) -> bool:
        machine_key = safe_text(machine_key)
        if not machine_key:
            raise ValueError("machine_key is required")
        with self._lock, closing(self._connect()) as conn:
            existing = conn.execute("SELECT 1 FROM machine_locks WHERE machine_key=? AND task_id=?", (machine_key, task_id)).fetchone()
            if existing:
                return True
            active = conn.execute("SELECT COUNT(*) FROM machine_locks WHERE machine_key=?", (machine_key,)).fetchone()[0]
            if active >= self.machine_limit(machine_key):
                return False
            conn.execute("INSERT INTO machine_locks (machine_key,task_id,acquired_at) VALUES (?,?,?)", (machine_key, task_id, time.time()))
            return True

    def release_machine(self, task_id: str, machine_key: str = "") -> None:
        with self._lock, closing(self._connect()) as conn:
            if machine_key:
                conn.execute("DELETE FROM machine_locks WHERE task_id=? AND machine_key=?", (task_id, machine_key))
            else:
                conn.execute("DELETE FROM machine_locks WHERE task_id=?", (task_id,))

    def cleanup(self, retention_days: int) -> None:
        if retention_days <= 0:
            return
        cutoff = time.time() - retention_days * 86400
        with self._lock, closing(self._connect()) as conn:
            conn.execute("DELETE FROM query_tasks WHERE completed_at IS NOT NULL AND completed_at < ?", (cutoff,))


def auto_round_dir(query_id: str, round_number: int, task_id: str = "") -> pathlib.Path:
    if round_number < 1:
        raise ValueError("round must be at least 1")
    base = auto_query_dir(query_id)
    return (base / f"task_{task_id}" if task_id else base) / f"round_{round_number}"


def auto_round_path(query_id: str, round_number: int, task_id: str = "") -> pathlib.Path:
    return auto_round_dir(query_id, round_number, task_id) / "round.json"


def write_auto_round(record: dict[str, Any]) -> None:
    write_json(auto_round_path(safe_text(record["query_id"]), int(record["round"]), safe_text(record.get("task_id"))), record)


def load_auto_round(query_id: str, round_number: int, task_id: str = "") -> dict[str, Any]:
    return read_json(auto_round_path(query_id, round_number, task_id))


def list_auto_rounds() -> list[dict[str, Any]]:
    if not AUTO_REPORTS_DIR.exists():
        return []
    records: list[dict[str, Any]] = []
    for round_path in AUTO_REPORTS_DIR.glob("query_*/**/round.json"):
        try:
            record = read_json(round_path)
            records.append({
                "task_id": safe_text(record.get("task_id")), "query_id": safe_text(record.get("query_id")),
                "round": int(record.get("round", 0)), "started_at": safe_text(record.get("started_at")),
                "completed_at": safe_text(record.get("completed_at")), "status": safe_text(record.get("status")),
                "item_count": len(record.get("items", [])),
            })
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda item: (item["started_at"], item["task_id"], item["round"]), reverse=True)


def is_registered_report_path(report_path: str) -> bool:
    for record in list_auto_rounds():
        try:
            round_record = load_auto_round(record["query_id"], record["round"], record["task_id"])
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if any(isinstance(item, dict) and safe_text(item.get("report_path")) == report_path for item in round_record.get("items", [])):
            return True
    return False


def execute_hsd_query(query_id: str) -> list[dict[str, Any]]:
    command = ["curl.exe", "--noproxy", "*", "--negotiate", "-u", ":", "-L", "-sS", f"https://hsdes-api.intel.com/rest/query/execution/{query_id}"]
    result = subprocess.run(command, cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"HSD query request failed (exit {result.returncode}): {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"HSD query returned no data: {safe_text(payload.get('message')) if isinstance(payload, dict) else 'unexpected response'}")
    return [row for row in payload["data"] if isinstance(row, dict)]


def machine_lock_prompt(task_id: str) -> str:
    command = f'py scripts\\ips_copilot_ui.py --task-lock --task-id "{task_id}" --machine-id "<registered-machine-id>" --action acquire --wait'
    release = f'py scripts\\ips_copilot_ui.py --task-lock --task-id "{task_id}" --machine-id "<registered-machine-id>" --action release'
    return f"""硬件资源协调（不可跳过）：完成非硬件预检和机器选择后、执行任何 SSH 写操作、flash、power cycle、串口控制或 MLC 前，使用最终选定的 inventory machine id 运行：`{command}`。命令等待数据库中该机器的容量；等待时不得执行硬件副作用。成功后才可进行硬件操作。无论成功、失败、取消或异常，必须在 finally 中运行：`{release}`。extract/consult 不得申请此锁。"""


def build_auto_execute_prompt(query_id: str, round_number: int, ips_id: str, task_id: str) -> str:
    summary_path = f"out\\{ips_id}\\auto_run_summary_{task_id}.json"
    return f"""请使用 ips-auto-flow skill，执行全自动 IPS 诊断任务。只处理 Query `{query_id}` 中当前 Open 的 IPS `{ips_id}`；平台、BKC 或机器不明确时必须 blocked，不得猜测或替代。Flash 失败后不得抓启动日志或运行 MLC。

{machine_lock_prompt(task_id)}

先读取 IPS 确认仍为 Open，完成提取、兼容机器和 BKC 选择。仅在问题需要硬件验证且全部前置检查通过时才进行硬件操作。产物保存在 `out\\{ips_id}\\`，并按 skill 向 owner 自动发送结果邮件。无论完成、阻塞、跳过或失败，最后保存 UTF-8 JSON 摘要到 `{summary_path}`（不得包含凭据或绝对路径）：
```json
{{"query_id":"{query_id}","round":{round_number},"ips_id":"{ips_id}","title":"<title>","diagnostic_type":"<type>","status":"completed|blocked|skipped|failed","test_completed":false,"report_path":"out\\{ips_id}\\<report>.md","owner":"<owner>","owner_notification_status":"sent|draft|not_sent|failed","owner_email_body":"<body>","completed_at":"<ISO 8601>"}}
```
"""


def load_auto_summary(query_id: str, round_number: int, ips_id: str, task_id: str, job_status: str, job_output: str) -> dict[str, Any]:
    summary_path = KIT_ROOT / "out" / ips_id / f"auto_run_summary_{task_id}.json"
    fallback = {"query_id": query_id, "round": round_number, "ips_id": ips_id, "title": "", "diagnostic_type": "全自动诊断", "status": "cancelled" if job_status == "cancelled" else "failed" if job_status == "failed" else "completed", "test_completed": False, "report_path": "", "owner": "", "owner_notification_status": "not_sent", "owner_email_body": "", "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        summary = read_json(summary_path)
        if safe_text(summary.get("query_id")) != query_id or int(summary.get("round")) != round_number or safe_text(summary.get("ips_id")) != ips_id:
            raise ValueError("summary identifiers do not match the current task")
        status = safe_text(summary.get("status")).lower()
        if status not in {"completed", "blocked", "skipped", "failed"}:
            raise ValueError("summary status is invalid")
        summary.update({"status": status, "test_completed": bool(summary.get("test_completed")), "title": safe_text(summary.get("title")), "diagnostic_type": safe_text(summary.get("diagnostic_type")) or "全自动诊断", "owner": safe_text(summary.get("owner")), "owner_notification_status": safe_text(summary.get("owner_notification_status")) or "not_sent", "owner_email_body": safe_text(summary.get("owner_email_body")), "completed_at": safe_text(summary.get("completed_at")) or fallback["completed_at"]})
        report_path = safe_text(summary.get("report_path"))
        summary["report_path"] = safe_report_path(report_path) if report_path else ""
        return summary
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        fallback["owner_email_body"] = f"自动化任务未生成可用摘要。\nUI 记录原因：{type(exc).__name__}: {exc}\n\nCopilot 输出：\n{job_output[-4000:]}"
        return fallback


def summarize_round(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"completed": 0, "blocked": 0, "skipped": 0, "failed": 0, "cancelled": 0}
    for item in items:
        status = safe_text(item.get("status")).lower()
        if status in counts:
            counts[status] += 1
    return counts


def send_round_notification(round_record: dict[str, Any], manager_recipients: str, report_base_url: str) -> None:
    recipients = safe_text(manager_recipients)
    if not recipients:
        round_record["manager_notification"] = {"status": "not_requested", "reason": "未填写汇总报告通知者。"}
        return
    summary_url = report_url(report_base_url, f"/reports/task/{round_record['task_id']}/{round_record['query_id']}/{round_record['round']}")
    if not summary_url:
        round_record["manager_notification"] = {"status": "not_sent", "reason": "未配置 server.reportBaseUrl，无法发送可访问的汇总报告链接。"}
        return
    counts = summarize_round(round_record["items"])
    body = f"Query {round_record['query_id']} 第 {round_record['round']} 轮已完成。\n\n处理时间：{round_record['started_at']} 至 {round_record['completed_at']}\nOpen IPS：{len(round_record['items'])}\n完成：{counts['completed']}；阻塞：{counts['blocked']}；跳过：{counts['skipped']}；失败：{counts['failed']}\n\n汇总报告：{summary_url}"
    command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(KIT_ROOT / "scripts" / "Send-OwnerNotification.ps1"), "-To", recipients, "-Subject", f"[Copilot][HSD] Query {round_record['query_id']} 第 {round_record['round']} 轮汇总已完成", "-Body", body, "-Send"]
    try:
        result = subprocess.run(command, cwd=str(KIT_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        status = "sent" if result.returncode == 0 and "NOTIFICATION_SENT=True" in result.stdout else "failed"
        output = (result.stdout + result.stderr)[-4000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        status, output = "failed", f"{type(exc).__name__}: {exc}"
    round_record["manager_notification"] = {"status": status, "recipients": recipients, "summary_url": summary_url, "output": output}


class TaskManager:
    def __init__(self, cfg: dict[str, Any]) -> None:
        automation = cfg.get("automation", {})
        database_path = pathlib.Path(automation.get("taskDatabasePath", "out\\ui_task_manager.sqlite3"))
        if not database_path.is_absolute():
            database_path = KIT_ROOT / database_path
        self.cfg = cfg
        self.store = TaskStore(database_path, automation.get("perMachineConcurrency", {"default": 1}))
        self.store.cleanup(int(automation.get("retentionDays", 90)))
        self._events: dict[str, threading.Event] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def start(self, query_id: str, creator_name: str, interval_minutes: int, manager_recipients: str) -> dict[str, Any]:
        query_id = require_numeric_id(query_id, "query_id")
        creator_name = safe_text(creator_name)
        if not creator_name:
            raise ValueError("creator_name is required")
        minimum = int(self.cfg.get("automation", {}).get("minimumIntervalMinutes", 60))
        if interval_minutes < minimum:
            raise ValueError(f"interval_minutes must be at least {minimum}")
        copilot_cfg = self.cfg.get("copilot", {})
        if copilot_cfg.get("mode") != "subprocess" or copilot_cfg.get("stage2Mode") != "subprocess":
            raise ValueError("全自动模式要求 copilot.mode 和 copilot.stage2Mode 均为 subprocess。")
        task = self.store.create_task(query_id, creator_name, interval_minutes, safe_text(manager_recipients), safe_text(self.cfg.get("server", {}).get("reportBaseUrl")))
        event = threading.Event()
        with self._lock:
            self._events[task["id"]] = event
        threading.Thread(target=self._worker, args=(task["id"], event), daemon=True).start()
        return task

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_tasks()

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.store.get_task(task_id)

    def cancel(self, task_id: str, reason: str = "Cancelled by user") -> dict[str, Any]:
        task = self.store.request_cancel(task_id, safe_text(reason) or "Cancelled by user")
        with self._lock:
            event = self._events.get(task_id)
            proc = self._processes.get(task_id)
        if event:
            event.set()
        if proc and proc.poll() is None:
            self._terminate_process(proc)
        return self.store.get_task(task_id) or task

    def _terminate_process(self, proc: subprocess.Popen[str]) -> None:
        grace = max(1, int(self.cfg.get("automation", {}).get("cancellationGraceSeconds", 15)))
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=grace)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            proc.kill()
        except OSError:
            pass

    def _worker(self, task_id: str, cancel_event: threading.Event) -> None:
        task = self.store.get_task(task_id)
        if task is None or task["status"] == "cancelled":
            return
        self.store.update(task_id, status="running", started_at=time.time())
        self.store.append_output(task_id, f"全自动任务已启动：Query {task['query_id']}，每 {task['interval_seconds'] // 60} 分钟轮询一次。")
        try:
            while not cancel_event.is_set():
                task = self.store.get_task(task_id)
                if task is None:
                    return
                try:
                    rows = execute_hsd_query(task["query_id"])
                    open_ids = sorted({safe_text(row.get("id")) for row in rows if safe_text(row.get("id")) and safe_text(row.get("status")).lower() == "open"})
                    round_number = int(task["current_round"]) + 1
                    self.store.update(task_id, current_round=round_number)
                    round_record = {"task_id": task_id, "query_id": task["query_id"], "round": round_number, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "completed_at": "", "status": "running", "items": [], "manager_notification": {"status": "pending"}}
                    write_auto_round(round_record)
                    self.store.append_output(task_id, f"第 {round_number} 轮查询完成：发现 {len(open_ids)} 个 Open IPS。")
                    processed = task.get("processed", {})
                    for ips_id in open_ids:
                        if cancel_event.is_set():
                            break
                        if ips_id in processed:
                            continue
                        self.store.update(task_id, current_ips_id=ips_id, status="running")
                        self.store.append_output(task_id, f"开始处理 IPS {ips_id}。")
                        try:
                            code, output = run_copilot(build_auto_execute_prompt(task["query_id"], round_number, ips_id, task_id), self.cfg, output_callback=lambda chunk: self.store.append_output(task_id, chunk), cancel_event=cancel_event, process_callback=lambda proc: self._set_process(task_id, proc))
                            job_status = "cancelled" if cancel_event.is_set() else "completed" if code == 0 else "failed"
                            item = load_auto_summary(task["query_id"], round_number, ips_id, task_id, job_status, output)
                        except Exception as exc:
                            item = {"query_id": task["query_id"], "round": round_number, "ips_id": ips_id, "title": "", "diagnostic_type": "全自动诊断", "status": "failed", "test_completed": False, "report_path": "", "owner": "", "owner_notification_status": "not_sent", "owner_email_body": f"UI 自动处理异常：{type(exc).__name__}: {exc}", "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                        finally:
                            self._clear_process(task_id)
                            self.store.release_machine(task_id)
                        round_record["items"].append(item)
                        write_auto_round(round_record)
                        processed[ips_id] = item.get("status", "failed")
                        self.store.update(task_id, processed_json=json.dumps(processed, ensure_ascii=False), current_ips_id="")
                        self.store.append_output(task_id, f"IPS {ips_id} 处理结束：{item['status']}。")
                    round_record["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    round_record["status"] = "cancelled" if cancel_event.is_set() else "completed"
                    if not cancel_event.is_set():
                        send_round_notification(round_record, task["manager_recipients"], task["report_base_url"])
                    else:
                        round_record["manager_notification"] = {"status": "not_sent", "reason": "任务已取消。"}
                    write_auto_round(round_record)
                    self.store.update(task_id, report_path=str(auto_round_path(task["query_id"], round_number, task_id).relative_to(KIT_ROOT)))
                except Exception as exc:
                    self.store.append_output(task_id, f"本轮查询或处理失败：{type(exc).__name__}: {exc}")
                if not cancel_event.wait(task["interval_seconds"]):
                    continue
        finally:
            self.store.release_machine(task_id)
            current = self.store.get_task(task_id)
            if current and current["status"] not in TERMINAL_TASK_STATUSES:
                if cancel_event.is_set() or current["status"] == "cancelling":
                    self.store.update(task_id, status="cancelled", completed_at=time.time(), current_ips_id="")
                else:
                    self.store.update(task_id, status="completed", completed_at=time.time(), current_ips_id="")
            self.store.append_output(task_id, "全自动任务已停止。")
            with self._lock:
                self._events.pop(task_id, None)
                self._processes.pop(task_id, None)

    def _set_process(self, task_id: str, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes[task_id] = proc
        self.store.update(task_id, process_id=proc.pid)

    def _clear_process(self, task_id: str) -> None:
        with self._lock:
            self._processes.pop(task_id, None)
        self.store.update(task_id, process_id=None)


TASK_MANAGER: TaskManager | None = None

def task_type_label(form: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    explicit = safe_text(form.get("task_type_label"))
    if explicit:
        return explicit
    task_type = safe_text(form.get("task_type"))
    if cfg:
        for item in cfg.get("taskTypes", []):
            if item.get("id") == task_type:
                return f"{item.get('label', task_type)} - {item.get('description', '')}".strip()
    labels = {
        "extract_ips": "提取 IPS - 只提取 HSD/IPS 信息并生成分析，不执行硬件动作。",
        "consult": "问题咨询 - 基于 HSD/IPS 和备注生成咨询分析，不执行硬件动作。",
        "debug_repro": "Debug / 验证 - 用户确认后执行 BKC 匹配、烧录、抓日志、MLC 和报告。",
    }
    return labels.get(task_type, task_type)


def permission_label(form: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    explicit = safe_text(form.get("permission_label"))
    if explicit:
        return explicit
    level = safe_text(form.get("permission_level"))
    if cfg:
        for item in cfg.get("permissionLevels", []):
            if item.get("id") == level:
                return f"{item.get('label', level)} - {item.get('description', '')}".strip()
    labels = {
        "standard": "标准授权 - 执行前对高风险动作保持谨慎确认。",
        "trusted_plan": "信任已确认计划 - 对用户确认计划内的低风险命令尽量不反复询问。",
        "maximum": "最高授权 - 对用户确认计划内的命令尽量自主执行；不能绕过 Copilot CLI/OS 安全限制。",
    }
    return labels.get(level, level or "standard")


def initial_plan_text(form: dict[str, Any]) -> str:
    article_id = safe_text(form.get("ips_id"))
    automatic_machine_match = bool(form.get("auto_machine_match"))
    ssh_host = (
        "自动匹配（阶段2根据 IPS/HSD 平台环境选择）"
        if automatic_machine_match
        else safe_text(form.get("ssh_host"))
    )
    task_type = safe_text(form.get("task_type"))
    notes = safe_text(form.get("notes"))
    test_target = safe_text(form.get("test_target"))
    output_dir = safe_text(form.get("output_dir")) or "out"
    report_dir = f"{output_dir}\\{article_id}" if article_id else f"{output_dir}\\<IPS_HSD_ID>"
    task_label = task_type_label(form)
    permission = permission_label(form)
    similar_ips = bool(form.get("search_similar_ips"))
    download_attachments = bool(form.get("download_attachments"))
    notify_owner = True
    notify_recipient = "HSD/IPS owner"
    notify_auto_send = bool(form.get("notify_auto_send"))
    similar_step = "并检索相似 IPS/HSD 获取历史经验" if similar_ips else "不检索相似 IPS/HSD"
    attachment_step = "并下载/分析客户附件包（如有）" if download_attachments else "不下载客户附件"
    notify_mode = "自动发送" if notify_auto_send else "生成 Outlook 草稿"
    notify_step = f"阶段2完成后{notify_mode}给 {notify_recipient}；邮件正文提供客户机器环境、客户问题、诊断结果、重点关注、下一步研究方向和完整报告路径" if notify_owner else "不发送完成通知"
    machine_selection_step = (
        "根据提取出的平台/机型、socket 拓扑和测试类型，读取 `config\\lab-machine-inventory.json` 自动选择兼容控制机；平台不明或冲突时停止并报告，不得猜测或跨平台替代。"
        if automatic_machine_match
        else f"使用用户手动选择的 SSH 控制机 `{ssh_host or '<未填写>'}`，并在硬件操作前验证该机与 IPS/HSD 平台匹配。"
    )

    if task_type == "debug_repro":
        planned_steps = """1. 阶段2开始后，读取 IPS/HSD {article_id} 的详细内容。
2. 提取问题、owner、BKC/软件版本、平台配置、客户复现步骤和历史评论。
3. {machine_selection_step}
4. {similar_step}。
5. {attachment_step}。
6. 根据 BKC 和平台匹配远端 .bin 镜像，并显示候选 bin、大小、SHA256。
7. 用户确认的情况下执行烧录；烧录失败则停止并诊断。
8. 烧录成功后抓取匹配的 CPU/BMC 串口启动日志。
9. 启动成功后运行 MLC 或用户指定测试：{test_target}。
10. 将 Markdown 报告、原始日志、测试结果和附件统一保存到 `{report_dir}`。
11. {notify_step}。""".format(
            article_id=article_id or "<IPS/HSD ID>",
            test_target=test_target or "根据 IPS/HSD 问题自动选择",
            machine_selection_step=machine_selection_step,
            similar_step=similar_step,
            attachment_step=attachment_step,
            notify_step=notify_step,
            report_dir=report_dir,
        )
    elif task_type == "consult":
        planned_steps = """1. 阶段2开始后，读取 IPS/HSD {article_id} 的详细内容。
2. 提取问题背景、owner、平台、BKC/软件版本、客户疑问和历史评论。
3. {similar_step}。
4. {attachment_step}。
5. 结合用户备注进行问题咨询分析。
6. 将 Markdown 咨询报告、HSD 提取结果和附件统一保存到 `{report_dir}`，并输出建议、可能原因、需要补充的信息和下一步建议。
7. {notify_step}。
8. 不执行烧录、power cycle、串口、MLC 或任何硬件动作。""".format(
            article_id=article_id or "<IPS/HSD ID>",
            similar_step=similar_step,
            attachment_step=attachment_step,
            notify_step=notify_step,
            report_dir=report_dir,
        )
    else:
        planned_steps = """1. 阶段2开始后，读取 IPS/HSD {article_id} 的详细内容。
2. 提取 title、owner、status、family/release/component、BKC/软件版本、问题描述、复现步骤、fix/root cause/workaround。
3. {similar_step}。
4. {attachment_step}。
5. 将 Markdown 分析报告、HSD 提取结果和附件统一保存到 `{report_dir}`，并输出结构化摘要。
6. {notify_step}。
7. 不执行烧录、power cycle、串口、MLC 或任何硬件动作。""".format(
            article_id=article_id or "<IPS/HSD ID>",
            similar_step=similar_step,
            attachment_step=attachment_step,
            notify_step=notify_step,
            report_dir=report_dir,
        )

    return f"""# 待确认任务计划

> 阶段一说明：本计划仅根据 UI 表单字段生成，尚未访问 HSD/IPS，尚未连接 SSH，也没有执行任何硬件动作。

## 用户输入

- IPS/HSD ID：{article_id}
- SSH 控制机：{ssh_host}
- 自动机器匹配：{"是" if automatic_machine_match else "否"}
- 功能类型 ID：{task_type}
- 功能类型说明：{task_label}
- 授权级别：{permission}
- 检索相似 IPS：{"是" if similar_ips else "否"}
- 下载并分析客户附件：{"是" if download_attachments else "否"}
- 完成后通知：是
- 通知收件人：HSD/IPS owner
- 通知方式：{notify_mode}
- 测试目标：{test_target or "根据 HSD 问题自动选择"}
- 报告及任务产物目录：{report_dir}
- 补充信息：{notes or "无"}

## AI 对用户需求的理解

- 用户希望处理 IPS/HSD：{article_id or "<未填写>"}。
- 用户选择的功能是：{task_label or "<未选择>"}。
- 用户选择的授权级别是：{permission}。
- 用户选择{"需要" if similar_ips else "不需要"}检索相似 IPS/HSD 获取历史经验。
- 用户选择{"需要" if download_attachments else "不需要"}下载并分析客户附件。
- 阶段2完成后默认通知 HSD/IPS owner。
- 用户指定或建议的 SSH 控制机是：{ssh_host or "<未填写>"}。
- 用户补充要求是：{notes or "无"}。

## 建议执行计划

{planned_steps}

## 安全检查

- 阶段1只生成计划，不能读取 HSD/IPS，不能 SSH，不能烧录，不能 power cycle，不能串口控制，不能运行 MLC。
- 阶段2执行硬件动作前必须由用户在 UI 中勾选确认。
- 授权级别只表达用户意图，不能绕过 Copilot CLI、操作系统、SSH、硬件设备或安全策略本身的权限限制。
- 烧录前确认 hostname/IP 与目标平台匹配。
- 烧录前显示并确认 bin 路径、大小和 SHA256。
- Flash 失败必须停止，不进入抓日志阶段。
- 保存完整原始日志后再分析。
"""


def build_plan_prompt(form: dict[str, Any], cfg: dict[str, Any]) -> str:
    text_template = initial_plan_text(form)
    task_label = task_type_label(form, cfg)
    permission = permission_label(form, cfg)
    similar_ips = "是" if form.get("search_similar_ips") else "否"
    download_attachments = "是" if form.get("download_attachments") else "否"
    notify_owner = "是"
    notify_recipient = "HSD/IPS owner"
    notify_auto_send = "是" if form.get("notify_auto_send") else "否"
    automatic_machine_match = bool(form.get("auto_machine_match"))
    ssh_host = (
        "自动匹配（阶段2根据 IPS/HSD 平台环境选择）"
        if automatic_machine_match
        else safe_text(form.get("ssh_host"))
    )
    plan_only_text = cfg.get("defaults", {}).get(
        "planOnlyNoHardwareText",
        "阶段1只能根据UI字段生成计划，严禁访问HSD/SSH或执行硬件动作。",
    )
    return f"""请使用 ips-ui-plan-stage skill。

你现在处于【阶段1：只根据 UI 表单字段理解需求并生成执行计划】。

重要安全限制：
{plan_only_text}

请严格遵守：
1. 不要调用任何工具。
2. 不要访问 HSD database。
3. 不要 SSH 连接任何机器。
4. 不要读取 BKC 文件夹。
5. 不要烧录、power cycle、打开串口、运行 MLC。
6. 你只需要根据 UI 表单字段，思考用户想做什么，然后输出下一步执行计划。

UI 表单字段如下，请完整体现在计划中：

| 字段 | 值 |
| --- | --- |
| IPS/HSD ID | {safe_text(form.get("ips_id"))} |
| 自动机器匹配 | {"是" if automatic_machine_match else "否"} |
| SSH 控制机 | {ssh_host} |
| 功能类型 ID | {safe_text(form.get("task_type"))} |
| 功能类型说明 | {task_label} |
| 授权级别 | {permission} |
| 检索相似 IPS | {similar_ips} |
| 下载并分析客户附件 | {download_attachments} |
| 完成后通知 | {notify_owner} |
| 通知收件人 | {notify_recipient} |
| 自动发送邮件 | {notify_auto_send} |
| 测试目标 | {safe_text(form.get("test_target"))} |
| 输出目录 | {safe_text(form.get("output_dir"))} |

补充信息：
{safe_text(form.get("notes"))}

请完成：
1. 根据功能类型判断后续是否需要硬件动作。
2. 如果功能类型是“问题咨询/consult”，计划中必须明确：只在阶段2读取 IPS/HSD 并做分析建议，不需要烧录和实际测试。
3. 如果功能类型是“提取 IPS/extract_ips”，计划中必须明确：只在阶段2读取 IPS/HSD 并提取摘要，不需要烧录和实际测试。
4. 如果功能类型是“Debug / 验证/debug_repro”，计划中才可以包含 BKC 匹配、烧录、启动日志、MLC/指定测试。
5. 如果用户填写了 IPS/HSD ID、机器匹配模式、SSH 控制机、测试目标或备注，必须在计划中原样体现。
6. 如果用户选择自动机器匹配，计划中必须说明：阶段2读取 IPS/HSD 后，依据 `config\\lab-machine-inventory.json` 的平台别名、能力与阻断规则选择机器；平台未知或冲突时停止并报告，不得猜测或跨平台替代。
7. 如果用户选择了高授权或最高授权，计划中要说明：该授权只适用于阶段2中“用户已确认计划内”的命令，且不能绕过 Copilot CLI/OS/SSH/硬件安全限制。
8. 如果用户选择“检索相似 IPS”，计划中要包含：阶段2读取目标 IPS 后，基于 title/component/family/suspected_problem_area/关键词检索相似 IPS，提取可复用经验、root cause、workaround、fix 或评论线索。
9. 如果用户选择“下载并分析客户附件”，计划中要包含：阶段2解析 HSD 附件字段（ext_attach_url/download_attached_ips_files），尝试通过 Kerberos/curl 下载附件包，统一保存到 `out\\<IPS_HSD_ID>\\attachments\\`，解压并优先分析 Overview/README/summary/config/log 文件；如果无法下载或无权限，需要在报告中说明。
10. 计划中要包含：阶段2完成报告后默认通知 HSD/IPS owner；邮件标题需要包含 `[Copilot][HSD]`、HSD ID、任务类型和简短状态。邮件正文必须是便于工作人员快速判断和跟进的独立摘要，而不是 Markdown 报告目录或路径列表：按“客户机器环境”“客户问题”“诊断结果”“重点关注”“下一步研究方向”“完整报告”六个标题组织。客户机器环境应提取平台/机型、拓扑、BKC/BIOS、OS、测试工具和关键配置；未获取的信息明确标注“未获取”。诊断结果必须说明复现/验证状态、最终结论和关键证据。重点关注必须列出风险、限制或尚未验证的假设。下一步研究方向必须给出可执行的后续验证或信息收集项。完整 Markdown 报告仍作为附件，并在正文末尾列出报告路径。{"如果用户选择自动发送，阶段2调用通知脚本时需要加 -Send；否则只显示 Outlook 草稿。" if form.get("notify_auto_send") else "默认只显示 Outlook 草稿，不自动发送。"}
11. 输出给使用者看的自然语言计划，可以使用 Markdown 表格/列表。

请不要输出 JSON。请输出清晰、可读、便于使用者检查和修改的中文文本。

输出结构参考：
{text_template}
"""


def choose_stage2_skill(plan_text: str, task_type: str = "") -> str:
    task_type = safe_text(task_type).lower()
    if task_type in ("consult", "extract_ips"):
        return "ips-consult-flow"
    if task_type == "debug_repro":
        return "ips-hsd-repro-flow"
    lowered = plan_text.lower()
    if "consult" in lowered or "问题咨询" in plan_text or "咨询" in plan_text:
        return "ips-consult-flow"
    if "extract_ips" in lowered or "提取 ips" in lowered or "提取ips" in lowered:
        return "ips-consult-flow"
    if "不执行硬件" in plan_text or "不需要烧录" in plan_text or "不运行 mlc" in lowered:
        return "ips-consult-flow"
    return "ips-hsd-repro-flow"


def build_execute_prompt(
    plan_text: str,
    cfg: dict[str, Any],
    permission: str = "",
    task_type: str = "",
    auto_machine_match: bool = False,
    ssh_host: str = "",
) -> str:
    permission_text = permission or "未单独指定；以最终执行计划中的授权级别为准。"
    stage2_skill = choose_stage2_skill(plan_text, task_type)
    machine_instruction = (
        """用户启用了自动机器匹配。读取 IPS/HSD 提取出的平台/机型、socket 拓扑和测试类型后，必须读取 `docs\\lab_machine_inventory.md` 与 `config\\lab-machine-inventory.json`，选择平台兼容且具备所需能力的控制机。GNR/BHS 与 DMR/Oak Stream 不得互相替代；平台未知或冲突时停止并报告需要补充的信息。报告中记录最终选择的机器、理由和能力检查结果。"""
        if auto_machine_match
        else f"""用户手动选择的 SSH 控制机是：`{ssh_host or '<未填写>'}`。只能使用该机器，并在硬件操作前验证它与 IPS/HSD 的平台、BKC 和测试需求匹配；不匹配时停止并报告，不能自动切换机器。"""
    )
    return f"""请使用 {stage2_skill} skill，进入【阶段2：执行用户确认后的计划】。

用户已经在 UI 中完成二次确认，并确认下面文本是最终执行计划。

用户选择的执行授权级别：
{permission_text}

执行要求：
1. 按最终执行计划中的用户意图执行；如果某一步被用户删除或明确禁用，不要执行。
2. 如果这是 consult / 问题咨询任务：只读取 IPS/HSD 并生成咨询分析报告，不要 SSH、不要 BKC 匹配用于烧录、不要烧录、不要 power cycle、不要串口、不要 MLC。
3. 如果这是 debug_repro / Debug 验证任务：如果涉及烧录，必须先确认 hostname/IP、bin 路径、bin size、SHA256、EM100/PowerSplitter/COM 口状态。
4. {machine_instruction}
5. {machine_lock_prompt("{resource_task_id}") if task_type == "debug_repro" else "这是 extract/consult 任务：不得申请硬件资源锁，也不得执行硬件操作。"}
6. Flash 失败必须停止并诊断，不允许继续抓启动日志。
7. 保存完整原始日志，再分析。
8. 从最终计划确定 IPS/HSD ID，并将 Markdown 报告、HSD 提取文件、附件、原始日志和测试结果统一保存到 `out\\<IPS_HSD_ID>\\`；不要直接将本次任务的产物保存到 `out\\` 根目录。报告包含 HSD 摘要、复现/咨询步骤、结果、解决程度和初步原因推测。
9. 如果最终计划要求检索相似 IPS/HSD：先读取目标 IPS，再基于 title/component/family/suspected_problem_area/关键词检索相似问题，提取可复用经验并写入报告；如果检索结果噪声大，需要说明筛选依据和不确定性。
10. 如果最终计划要求下载并分析客户附件：解析 HSD 附件字段，尝试下载附件包，保存到 `out\\<IPS_HSD_ID>\\attachments\\`，解压并优先分析 Overview/README/summary/config/log；如果失败，报告中说明失败原因和可手动下载的链接/字段。
11. 如果最终计划要求完成后通知：报告生成后调用 `scripts\\Send-OwnerNotification.ps1` 生成/发送通知。默认收件人必须从 HSD/IPS 的 owner 字段解析。邮件 Subject 需要包含 `[Copilot][HSD]`、HSD ID、任务类型和简短状态。邮件 Body 必须直接提供工作人员可阅读的诊断摘要，不能只写“结论摘要”和报告路径；使用以下固定结构：
   ```text
   HSD/IPS ID: <id>
   标题: <title>
   Owner: <owner>
   任务类型: <consult/extract/debug>

   客户机器环境
   - 平台/机型、socket/NUMA 或 DIMM 拓扑、BKC/BIOS、OS、测试工具/版本、关键配置；没有可靠证据的字段写“未获取”，不可猜测。

   客户问题
   - 客户现象、影响和明确诉求。

   诊断结果
   - 复现/验证状态、最终结论、支撑结论的关键证据，以及是否执行硬件动作。

   重点关注
   - 风险、限制、未验证假设、结果与客户环境的差异或需要人工决策的事项。

   下一步研究方向
   - 可执行的后续验证、配置对比、日志/信息收集或责任人跟进项；若无需后续动作，明确说明原因。

   完整报告
   - Markdown 报告已作为附件：<report path>
   ```
   内容要简明、面向行动，完整技术细节保留在 Markdown 附件中。若运行了 MLC，调用脚本时必须添加 `-IncludeMlcResults`，将完整 `host_mlc_results.log` 与报告一并附件；未运行 MLC 时不得添加此开关。若计划写明“自动发送邮件：是”，调用脚本时添加 `-Send`；否则不要添加 `-Send`，只显示 Outlook 草稿。
12. 如果授权级别为高授权或最高授权：对最终计划内、必要且低歧义的命令行步骤尽量连续执行，不要对每个普通命令反复询问；但仍必须遵守 Copilot CLI/OS/SSH/硬件安全限制，遇到破坏性、超出计划、目标不明确或高风险动作时应停止确认。

最终执行计划：
{plan_text}
"""


def run_copilot(
    prompt: str,
    cfg: dict[str, Any],
    job_id: str | None = None,
    output_callback: Any = None,
    cancel_event: threading.Event | None = None,
    process_callback: Any = None,
) -> tuple[int, str]:
    copilot_cfg = cfg.get("copilot", {})
    mode = copilot_cfg.get("mode", "manual")
    if mode != "subprocess":
        return 0, (
            "MANUAL MODE: 当前配置不会直接调用 Copilot CLI。\n"
            "请复制下面的 prompt 到 Copilot CLI 中执行，或将 config\\ips-copilot-ui.template.json "
            "中的 copilot.mode 改为 subprocess。\n\n"
            + prompt
        )

    command = list(copilot_cfg.get("command") or [])
    if not command:
        return 2, "copilot.command is empty."

    timeout = int(copilot_cfg.get("timeoutSeconds", 7200))
    pass_prompt = copilot_cfg.get("passPrompt", "stdin")
    cwd = copilot_cfg.get("workingDirectory", ".")
    cwd_path = (KIT_ROOT / cwd).resolve() if not os.path.isabs(cwd) else pathlib.Path(cwd)
    encoding = copilot_cfg.get("promptFileEncoding", "utf-8")
    prepend_commands = [safe_text(item) for item in copilot_cfg.get("prependCommands", []) if safe_text(item)]
    prompt_to_send = ("\n".join(prepend_commands) + "\n\n" + prompt) if prepend_commands else prompt

    prompt_file = None
    try:
        if "{prompt_file}" in " ".join(command) or pass_prompt == "promptFile":
            tmp = tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                suffix=".txt",
                prefix=f"copilot_prompt_{job_id}_",
                encoding=encoding,
            )
            tmp.write(prompt_to_send)
            tmp.close()
            prompt_file = tmp.name
            command = [part.replace("{prompt_file}", prompt_file) for part in command]
            if "{prompt_file}" not in " ".join(command):
                command.append(prompt_file)
            stdin_data = None
        elif pass_prompt == "argument":
            command.append(prompt_to_send)
            stdin_data = None
        else:
            stdin_data = prompt_to_send

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            command,
            cwd=str(cwd_path),
            stdin=subprocess.PIPE if stdin_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        if process_callback:
            process_callback(proc)
        output_queue: queue.Queue[str] = queue.Queue()

        def reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                output_queue.put(line)

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        if stdin_data is not None and proc.stdin is not None:
            proc.stdin.write(stdin_data)
            proc.stdin.close()

        output_parts: list[str] = []
        deadline = time.time() + timeout
        while True:
            try:
                while True:
                    chunk = output_queue.get_nowait()
                    output_parts.append(chunk)
                    if job_id:
                        append_job_output(job_id, chunk)
                    if output_callback:
                        output_callback(chunk)
            except queue.Empty:
                pass

            code = proc.poll()
            if code is not None:
                reader_thread.join(timeout=2)
                try:
                    while True:
                        chunk = output_queue.get_nowait()
                        output_parts.append(chunk)
                        if job_id:
                            append_job_output(job_id, chunk)
                        if output_callback:
                            output_callback(chunk)
                except queue.Empty:
                    pass
                return code, "".join(output_parts)

            if time.time() > deadline:
                proc.kill()
                return 124, "".join(output_parts) + "\nTIMEOUT: Copilot command exceeded timeout.\n"

            if cancel_event is not None and cancel_event.is_set():
                grace = max(1, int(cfg.get("automation", {}).get("cancellationGraceSeconds", 15)))
                try:
                    if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        proc.terminate()
                    proc.wait(timeout=grace)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        proc.kill()
                    except OSError:
                        pass
                return 130, "".join(output_parts) + "\nCANCELLED: Copilot command was terminated.\n"

            time.sleep(0.2)
    finally:
        if prompt_file and os.path.exists(prompt_file):
            try:
                os.remove(prompt_file)
            except OSError:
                pass


def append_job_output(job_id: str, text: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not None:
            job["output"] = job.get("output", "") + text
            job["updated_at"] = time.time()


def create_handoff(prompt: str, cfg: dict[str, Any], job_id: str) -> str:
    copilot_cfg = cfg.get("copilot", {})
    handoff_dir_text = copilot_cfg.get("handoffDirectory", "inbox\\ui_tasks")
    handoff_dir = (KIT_ROOT / handoff_dir_text).resolve() if not os.path.isabs(handoff_dir_text) else pathlib.Path(handoff_dir_text)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    task_path = handoff_dir / f"ui_stage2_task_{stamp}_{job_id[:8]}.md"
    task_path.write_text(prompt, encoding="utf-8")
    prepend_commands = [safe_text(item) for item in copilot_cfg.get("prependCommands", []) if safe_text(item)]
    prep_text = "\n".join(prepend_commands) if prepend_commands else "/allow-all"
    return f"""STAGE2_HANDOFF_CREATED

阶段二任务已保存，但没有在 UI 子进程中直接执行。

原因：
UI 通过 subprocess 启动的 Copilot CLI 可能没有当前会话的 shell/tool 权限，无法可靠执行 SSH、PowerShell、烧录、串口、MLC 等动作。

请在当前有工具权限的 Copilot CLI 会话中发送下面这句话：

{prep_text}

请读取并执行 UI 确认后的阶段二任务：{task_path}

任务文件：
{task_path}

如果你只想查看 prompt，也可以直接打开该文件。
"""


def start_job(kind: str, prompt: str, cfg: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    prompt = prompt.replace("{resource_task_id}", job_id)
    copilot_cfg = cfg.get("copilot", {})
    if kind == "execute" and copilot_cfg.get("stage2Mode", "handoff") == "handoff":
        output = create_handoff(prompt, cfg, job_id)
        with JOBS_LOCK:
            JOBS[job_id] = {
                "id": job_id,
                "kind": kind,
                "status": "completed",
                "exit_code": 0,
                "output": output,
                "prompt": prompt,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
        return job_id

    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "exit_code": None,
            "output": "",
            "prompt": prompt,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    def worker() -> None:
        try:
            code, output = run_copilot(prompt, cfg, job_id)
            with JOBS_LOCK:
                job = JOBS[job_id]
                if not job.get("output"):
                    job["output"] = output
                job["exit_code"] = code
                job["status"] = "completed" if code == 0 else "failed"
                job["updated_at"] = time.time()
        except Exception as exc:  # surface UI/backend errors rather than hiding them
            with JOBS_LOCK:
                job = JOBS[job_id]
                job["status"] = "failed"
                job["exit_code"] = 1
                job["output"] = job.get("output", "") + f"\nUI_BACKEND_ERROR: {type(exc).__name__}: {exc}\n"
                job["updated_at"] = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return job_id


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>IPS/HSD Copilot UI</title>
  <style>
    body { font-family: "Segoe UI", Arial, sans-serif; margin: 24px; color: #222; }
    h1 { margin-bottom: 4px; }
    .subtitle { color: #666; margin-top: 0; }
    .grid { display: grid; grid-template-columns: 180px 1fr; gap: 10px 14px; max-width: 1120px; }
    label { font-weight: 600; padding-top: 8px; }
    input, select, textarea { font-family: Consolas, "Segoe UI", monospace; font-size: 14px; padding: 8px; border: 1px solid #bbb; border-radius: 4px; }
    textarea { width: 100%; min-height: 110px; box-sizing: border-box; }
    button { padding: 9px 14px; border: 0; border-radius: 4px; cursor: pointer; margin-right: 8px; }
    button.primary { background: #0969da; color: white; }
    button.danger { background: #d1242f; color: white; }
    button.secondary { background: #eaeef2; color: #222; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .panel { border: 1px solid #d0d7de; border-radius: 6px; padding: 16px; margin-top: 18px; max-width: 1120px; }
    .status { font-weight: 600; }
    .warn { color: #9a6700; }
    .ok { color: #1a7f37; }
    .fail { color: #cf222e; }
    pre { background: #f6f8fa; border: 1px solid #d0d7de; padding: 12px; overflow: auto; max-height: 420px; white-space: pre-wrap; }
    #planText { min-height: 360px; }
    .small { font-size: 12px; color: #666; }
    .row { margin: 10px 0; }
    .hidden { display: none; }
    .auto-only { max-width: 720px; }
    .report-link { margin-left: 12px; }
  </style>
</head>
<body>
  <h1>IPS/HSD Copilot UI</h1>
  <p class="subtitle">支持两阶段手动流程，以及按 HSD Query 自动处理 Open IPS 的全自动模式。</p>

  <div class="panel">
    <div class="grid">
      <label for="uiMode">UI 模式</label>
      <select id="uiMode" onchange="updateUiMode()">
        <option value="simple">简洁模式：填写后直接开始执行</option>
        <option value="detailed">详细模式：先确认执行计划再执行</option>
        <option value="automatic">全自动模式：按 Query 定时处理 Open IPS</option>
      </select>
    </div>
  </div>

  <div class="panel manual-only">
    <h2>1. 输入任务信息</h2>
    <div class="grid">
      <label for="ipsId">IPS/HSD ID</label>
      <input id="ipsId" placeholder="例如 14025984558">

      <label for="autoMachineMatch">机器选择方式</label>
      <label style="font-weight: normal;"><input type="checkbox" id="autoMachineMatch" onchange="updateMachineSelection()"> 自动匹配机器（根据 IPS/HSD 提取的平台环境选择）</label>

      <label for="sshHost">SSH 控制机</label>
      <div>
        <select id="sshHost"></select>
        <div id="machineSelectionHint" class="small"></div>
      </div>

      <label for="taskType">功能类型</label>
      <select id="taskType"></select>

      <label for="permissionLevel">执行授权级别</label>
      <select id="permissionLevel"></select>

      <label for="searchSimilarIps">相似 IPS 检索</label>
      <label style="font-weight: normal;"><input type="checkbox" id="searchSimilarIps"> 检索相似 IPS 获取历史经验</label>

      <label for="downloadAttachments">客户附件</label>
      <label style="font-weight: normal;"><input type="checkbox" id="downloadAttachments"> 下载并分析客户附件</label>

      <label for="notifyAutoSend">通知发送方式</label>
      <label style="font-weight: normal;"><input type="checkbox" id="notifyAutoSend"> 自动发送给 HSD owner（不勾选则生成 Outlook 草稿）</label>

      <label for="testTarget">测试目标</label>
      <input id="testTarget" placeholder="例如 跨NUMA MLC bandwidth_matrix / boot only / 指定命令">

      <label for="outputDir">报告输出目录</label>
      <input id="outputDir" value="out">

      <label for="notes">备注 / 补充信息</label>
      <textarea id="notes" placeholder="例如：只分析不烧录；需要 MLC v3.11b；需要对比 Directory Mode；抓日志 10 分钟"></textarea>
    </div>
    <div class="row">
      <button id="simpleStartButton" class="primary" onclick="startSimple()">开始执行</button>
      <button class="secondary detailed-only" onclick="renderPlanPrompt()">预览阶段1 Prompt</button>
      <button class="primary detailed-only" onclick="startPlan()">生成执行计划</button>
    </div>
    <p class="small">简洁模式会直接按输入生成默认计划并执行；详细模式可先编辑确认执行计划。阶段二完成后默认通知 HSD owner。</p>
  </div>

  <div class="panel detailed-only manual-only">
    <h2>2. 阶段1 输出 / 执行计划</h2>
    <div>状态：<span id="planStatus" class="status">未开始</span></div>
    <pre id="planOutput"></pre>
    <div class="row">
      <button class="secondary" onclick="copyText('planOutput')">复制阶段1输出</button>
      <button class="secondary" onclick="useOutputAsPlan()">将阶段1输出填入文本计划编辑框</button>
    </div>

    <h3>可编辑文本计划</h3>
    <textarea id="planText"></textarea>
    <div class="row">
      <button class="secondary" onclick="resetPlanTemplate()">重置为默认文本计划模板</button>
      <span id="planEditStatus" class="small"></span>
    </div>
  </div>

  <div class="panel detailed-only manual-only">
    <h2>3. 二次确认并执行</h2>
    <p class="warn">只有勾选确认并点击“确认并执行”后，UI 才会启动阶段二 Copilot subprocess，并在下方输出框实时显示信息。</p>
    <label><input type="checkbox" id="confirmCheck"> 我已经检查并确认最终文本计划。</label>
    <div class="row">
      <button class="secondary" onclick="renderExecutePrompt()">预览阶段2 Prompt</button>
      <button class="danger" onclick="startExecute()">确认并执行</button>
    </div>
  </div>

  <div class="panel auto-only auto-run-only">
    <h2>全自动 Query 任务</h2>
    <p class="warn">每次启动都会创建独立、持久化的 Query 任务；多个 Query 可并行运行。相同已登记机器的硬件操作会在完成预检后协调串行。</p>
    <div class="grid">
      <label for="autoCreatorName">创建人姓名</label>
      <input id="autoCreatorName" placeholder="必填，例如 Zhang San">

      <label for="autoQueryId">HSD Query ID</label>
      <input id="autoQueryId" placeholder="例如 15019610126">

      <label for="autoIntervalMinutes">轮询间隔（分钟）</label>
      <input id="autoIntervalMinutes" type="number" min="60" step="1" value="60">

      <label for="autoManagerRecipients">汇总报告通知者</label>
      <input id="autoManagerRecipients" placeholder="Outlook 名称或邮箱；多个收件人以分号分隔">
    </div>
    <div class="row"><button class="danger" onclick="startQueryTask()">创建并启动 Query 任务</button>
      <a class="report-link" href="/reports" target="_blank" rel="noopener">查看历史汇总报告</a></div>
  </div>

  <div class="panel auto-only auto-run-only">
    <h2>共享 Query 任务管理</h2>
    <p class="small">所有浏览器会话看到相同的持久化状态。取消队列任务立即生效；运行中的 Copilot 子进程会先收到终止信号，超过配置宽限期后被强制结束。</p>
    <div id="taskList" class="small">正在加载任务…</div>
  </div>

  <div class="panel manual-only">
    <h2>执行输出</h2>
    <div>状态：<span id="execStatus" class="status">未开始</span></div>
    <pre id="execOutput"></pre>
    <button class="secondary" onclick="copyText('execOutput')">复制阶段2输出</button>
  </div>

<script>
let appConfig = null;
let lastPlanJob = null;
let lastExecJob = null;

async function api(path, payload) {
  const opts = payload === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  };
  const res = await fetch(path, opts);
  const text = await res.text();
  if (!res.ok) throw new Error(text);
  return JSON.parse(text);
}

function formData() {
  const taskType = document.getElementById("taskType");
  const autoMachineMatch = document.getElementById("autoMachineMatch").checked;
  const sshHost = document.getElementById("sshHost");
  return {
    ui_mode: document.getElementById("uiMode").value,
    ips_id: document.getElementById("ipsId").value,
    auto_machine_match: autoMachineMatch,
    ssh_host: autoMachineMatch ? "" : sshHost.value,
    ssh_machine_label: autoMachineMatch ? "自动匹配" : (sshHost.options[sshHost.selectedIndex] ? sshHost.options[sshHost.selectedIndex].textContent : ""),
    task_type: taskType.value,
    task_type_label: taskType.options[taskType.selectedIndex] ? taskType.options[taskType.selectedIndex].textContent : taskType.value,
    permission_level: document.getElementById("permissionLevel").value,
    permission_label: document.getElementById("permissionLevel").options[document.getElementById("permissionLevel").selectedIndex] ? document.getElementById("permissionLevel").options[document.getElementById("permissionLevel").selectedIndex].textContent : document.getElementById("permissionLevel").value,
    search_similar_ips: document.getElementById("searchSimilarIps").checked,
    download_attachments: document.getElementById("downloadAttachments").checked,
    notify_owner: true,
    notification_recipient_mode: "hsd_owner",
    notification_recipient: "",
    notify_auto_send: document.getElementById("notifyAutoSend").checked,
    notification_subject_prefix: "[Copilot][HSD]",
    test_target: document.getElementById("testTarget").value,
    output_dir: document.getElementById("outputDir").value,
    notes: document.getElementById("notes").value
  };
}

function setStatus(id, status) {
  const el = document.getElementById(id);
  el.textContent = status;
  el.className = "status " + (status === "completed" ? "ok" : status === "failed" ? "fail" : "");
}

async function loadConfig() {
  appConfig = await api("/api/config");
  document.getElementById("uiMode").value = appConfig.defaults.uiMode || "simple";
  const sshHost = document.getElementById("sshHost");
  sshHost.innerHTML = "";
  for (const machine of appConfig.machineOptions) {
    const opt = document.createElement("option");
    opt.value = machine.value;
    opt.textContent = machine.label;
    sshHost.appendChild(opt);
  }
  sshHost.value = appConfig.defaults.sshHost || "";
  if (!sshHost.value && sshHost.options.length) sshHost.selectedIndex = 0;
  document.getElementById("autoMachineMatch").checked = !!appConfig.defaults.autoMachineMatch;
  document.getElementById("taskType").innerHTML = "";
  for (const item of appConfig.taskTypes) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label + " - " + item.description;
    document.getElementById("taskType").appendChild(opt);
  }
  document.getElementById("taskType").value = appConfig.defaults.taskType || "debug_repro";
  document.getElementById("permissionLevel").innerHTML = "";
  for (const item of appConfig.permissionLevels || []) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label + " - " + item.description;
    document.getElementById("permissionLevel").appendChild(opt);
  }
  document.getElementById("permissionLevel").value = appConfig.defaults.permissionLevel || "standard";
  document.getElementById("notifyAutoSend").checked = !!appConfig.defaults.notifyAutoSend;
  document.getElementById("autoIntervalMinutes").min = appConfig.automation.minimumIntervalMinutes || 60;
  document.getElementById("autoIntervalMinutes").value = appConfig.automation.minimumIntervalMinutes || 60;
  document.getElementById("autoManagerRecipients").value = appConfig.automation.defaultManagerRecipients || "";
  updateUiMode();
  updateMachineSelection();
  resetPlanTemplate();
  refreshTasks();
}

function updateMachineSelection() {
  const automatic = document.getElementById("autoMachineMatch").checked;
  document.getElementById("sshHost").disabled = automatic;
  document.getElementById("machineSelectionHint").textContent = automatic
    ? "阶段2在提取 IPS/HSD 平台环境后，按已登记机器矩阵自动匹配；平台不明或冲突时会停止。"
    : "手动模式：阶段2只能使用此处选择的控制机，并会验证平台匹配。";
}

function updateUiMode() {
  const mode = document.getElementById("uiMode").value;
  const simple = mode === "simple";
  const automatic = mode === "automatic";
  for (const el of document.querySelectorAll(".manual-only")) {
    el.classList.toggle("hidden", automatic);
  }
  for (const el of document.querySelectorAll(".auto-run-only")) {
    el.classList.toggle("hidden", !automatic);
  }
  for (const el of document.querySelectorAll(".detailed-only")) {
    el.classList.toggle("hidden", simple || automatic);
  }
  document.getElementById("simpleStartButton").classList.toggle("hidden", !simple || automatic);
}

function taskHtml(task) {
  const report = task.report_path ? `<a href="/reports/task/${task.id}/${task.query_id}/${task.current_round}" target="_blank">本轮索引</a>` : "—";
  const cancel = ["queued", "running", "waiting_resource", "cancelling"].includes(task.status)
    ? `<button class="secondary" onclick="cancelQueryTask('${task.id}')" ${task.status === "cancelling" ? "disabled" : ""}>取消</button>` : "";
  return `<div class="panel" style="max-width:none;margin-top:10px"><b>${task.status}</b> · 创建人：${escapeHtml(task.creator_name)} · Query：${escapeHtml(task.query_id)} · 第 ${task.current_round} 轮 · 当前 IPS：${escapeHtml(task.current_ips_id || "—")} ${cancel}<br><span class="small">创建：${new Date(task.created_at * 1000).toLocaleString()}；原因：${escapeHtml(task.cancellation_reason || task.error_text || "—")}；${report}</span><pre>${escapeHtml(task.output || "")}</pre></div>`;
}
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = value || ""; return div.innerHTML; }
async function refreshTasks() {
  const data = await api("/api/tasks");
  document.getElementById("taskList").innerHTML = data.tasks.length ? data.tasks.map(taskHtml).join("") : "尚无 Query 任务。";
}
async function startQueryTask() {
  const queryId = document.getElementById("autoQueryId").value.trim();
  const creatorName = document.getElementById("autoCreatorName").value.trim();
  const intervalMinutes = Number(document.getElementById("autoIntervalMinutes").value);
  if (!creatorName) { alert("请输入创建人姓名。"); return; }
  if (!/^\d+$/.test(queryId)) { alert("请输入数字形式的 HSD Query ID。"); return; }
  await api("/api/tasks", {query_id: queryId, creator_name: creatorName, interval_minutes: intervalMinutes, manager_recipients: document.getElementById("autoManagerRecipients").value.trim()});
  refreshTasks();
}
async function cancelQueryTask(taskId) {
  const reason = window.prompt("取消原因（会持久化记录）：", "Cancelled by user");
  if (reason === null) return;
  await api(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {reason});
  refreshTasks();
}
setInterval(() => { if (document.getElementById("taskList")) refreshTasks().catch(() => {}); }, 1500);

async function resetPlanTemplate() {
  const data = await api("/api/plan-template", formData());
  document.getElementById("planText").value = data.plan_text;
  document.getElementById("planEditStatus").textContent = "已生成默认文本计划模板。";
}

async function renderPlanPrompt() {
  const data = await api("/api/render-plan-prompt", formData());
  document.getElementById("planOutput").textContent = data.prompt;
  setStatus("planStatus", "prompt rendered");
}

async function startPlan() {
  const data = await api("/api/start-plan", formData());
  lastPlanJob = data.job_id;
  setStatus("planStatus", "running");
  pollJob(lastPlanJob, "planStatus", "planOutput");
}

async function renderExecutePrompt() {
  const form = formData();
  const data = await api("/api/render-execute-prompt", {
    plan_text: document.getElementById("planText").value,
    permission_label: form.permission_label,
    task_type: form.task_type,
    auto_machine_match: form.auto_machine_match,
    ssh_host: form.ssh_host
  });
  document.getElementById("execOutput").textContent = data.prompt;
  setStatus("execStatus", "prompt rendered");
}

function validateExecutionConfirm() {
  if (!document.getElementById("confirmCheck").checked) {
    alert("请先勾选确认框。");
    return false;
  }
  if (!document.getElementById("planText").value.trim()) {
    alert("最终文本计划不能为空。");
    return false;
  }
  return true;
}

async function startExecute() {
  if (!validateExecutionConfirm()) return;
  const form = formData();
  const data = await api("/api/start-execute", {
    plan_text: document.getElementById("planText").value,
    permission_label: form.permission_label,
    task_type: form.task_type,
    auto_machine_match: form.auto_machine_match,
    ssh_host: form.ssh_host
  });
  lastExecJob = data.job_id;
  setStatus("execStatus", "running");
  pollJob(lastExecJob, "execStatus", "execOutput");
}

async function startSimple() {
  const form = formData();
  const plan = await api("/api/plan-template", form);
  const data = await api("/api/start-execute", {
    plan_text: plan.plan_text,
    permission_label: form.permission_label,
    task_type: form.task_type,
    auto_machine_match: form.auto_machine_match,
    ssh_host: form.ssh_host
  });
  lastExecJob = data.job_id;
  setStatus("execStatus", "running");
  document.getElementById("execOutput").textContent = "简洁模式已开始执行，完成后将按设置通知 HSD owner。";
  pollJob(lastExecJob, "execStatus", "execOutput");
}

async function pollJob(jobId, statusId, outputId) {
  while (true) {
    const data = await api("/api/job?id=" + encodeURIComponent(jobId));
    setStatus(statusId, data.status);
    document.getElementById(outputId).textContent = data.output || "";
    if (data.status === "completed" || data.status === "failed") {
      if (outputId === "planOutput" && data.status === "completed" && data.output) {
        document.getElementById("planText").value = data.output.trim();
        document.getElementById("planEditStatus").textContent = "阶段1输出已自动填入文本计划编辑框，可继续修改。";
      }
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
}

function useOutputAsPlan() {
  const output = document.getElementById("planOutput").textContent.trim();
  if (!output) return;
  const fenced = output.match(/```(?:markdown|text)?\s*([\s\S]*?)```/i);
  document.getElementById("planText").value = fenced ? fenced[1].trim() : output;
  document.getElementById("planEditStatus").textContent = "已填入阶段1输出，可继续手动修改。";
}

async function copyText(id) {
  await navigator.clipboard.writeText(document.getElementById(id).textContent);
}

loadConfig().catch(err => {
  document.body.innerHTML = "<pre>UI 初始化失败：" + err.message + "</pre>";
});
</script>
</body>
</html>
"""


def report_layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; margin: 28px; color: #24292f; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 9px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    .muted {{ color: #57606a; }}
    .status {{ font-weight: 600; }}
    pre {{ white-space: pre-wrap; background: #f6f8fa; border: 1px solid #d0d7de; padding: 14px; }}
    a {{ color: #0969da; }}
  </style>
</head>
<body>{body}</body>
</html>"""


def status_summary(items: list[dict[str, Any]]) -> str:
    counts = summarize_round(items)
    return f"完成 {counts['completed']}；阻塞 {counts['blocked']}；跳过 {counts['skipped']}；失败 {counts['failed']}"


def render_report_index() -> str:
    rows = []
    for record in list_auto_rounds():
        query_id = html.escape(record["query_id"])
        task_id = html.escape(record["task_id"])
        round_number = record["round"]
        report_href = (
            f"/reports/task/{task_id}/{query_id}/{round_number}"
            if task_id
            else f"/reports/{query_id}/{round_number}"
        )
        rows.append(
            "<tr>"
            f"<td>{task_id or '旧记录'}</td><td>{query_id}</td><td>第 {round_number} 轮</td>"
            f"<td>{html.escape(record['started_at'])}</td><td>{html.escape(record['completed_at'])}</td>"
            f"<td>{html.escape(record['status'])}</td><td>{record['item_count']}</td>"
            f'<td><a href="{report_href}">查看汇总</a></td></tr>'
        )
    table = "".join(rows) or '<tr><td colspan="8" class="muted">尚无全自动处理报告。</td></tr>'
    return report_layout(
        "全自动处理报告",
        f"""<h1>全自动处理报告</h1>
<p class="muted">每个 Query 轮次的处理结果会在本机保存，重启 UI 后仍可浏览。</p>
<table><thead><tr><th>任务 ID</th><th>Query ID</th><th>轮次</th><th>开始时间</th><th>完成时间</th><th>状态</th><th>IPS 数</th><th>报告</th></tr></thead>
<tbody>{table}</tbody></table>""",
    )


def render_round_report(query_id: str, round_number: int, task_id: str = "") -> str:
    record = load_auto_round(query_id, round_number, task_id)
    items = record.get("items", [])
    if not isinstance(items, list):
        raise ValueError("round items must be a list")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ips_id = html.escape(safe_text(item.get("ips_id")))
        detail_href = (
            f"/reports/task/{html.escape(task_id)}/{html.escape(query_id)}/{round_number}/{ips_id}"
            if task_id
            else f"/reports/{html.escape(query_id)}/{round_number}/{ips_id}"
        )
        rows.append(
            "<tr>"
            f"<td>{ips_id}</td><td>{html.escape(safe_text(item.get('title')) or '未获取')}</td>"
            f"<td>{html.escape(safe_text(item.get('diagnostic_type')))}</td>"
            f"<td>{'是' if item.get('test_completed') else '否'}</td>"
            f"<td class=\"status\">{html.escape(safe_text(item.get('status')))}</td>"
            f'<td><a href="{detail_href}">查看详情</a></td></tr>'
        )
    table = "".join(rows) or '<tr><td colspan="6" class="muted">本轮没有 Open IPS。</td></tr>'
    notification = record.get("manager_notification", {})
    notification_text = html.escape(safe_text(notification.get("status"))) if isinstance(notification, dict) else "未记录"
    return report_layout(
        f"Query {query_id} 第 {round_number} 轮处理报告",
        f"""<p><a href="/reports">返回历史汇总</a></p>
<h1>任务 {html.escape(task_id) or '旧记录'} · Query {html.escape(query_id)} · 第 {round_number} 轮处理报告</h1>
<p class="muted">处理时间：{html.escape(safe_text(record.get('started_at')))} 至 {html.escape(safe_text(record.get('completed_at')) or '进行中')}</p>
<p>整体状态：<span class="status">{html.escape(safe_text(record.get('status')))}</span>；{status_summary(items)}</p>
<p>管理汇总通知：<span class="status">{notification_text}</span></p>
<table><thead><tr><th>IPS ID</th><th>IPS 关键标题</th><th>诊断类型</th><th>是否完成测试</th><th>处理状态</th><th>详细报告</th></tr></thead>
<tbody>{table}</tbody></table>""",
    )


def render_report_detail(query_id: str, round_number: int, ips_id: str, task_id: str = "") -> str:
    record = load_auto_round(query_id, round_number, task_id)
    item = next(
        (
            candidate for candidate in record.get("items", [])
            if isinstance(candidate, dict) and safe_text(candidate.get("ips_id")) == ips_id
        ),
        None,
    )
    if item is None:
        raise FileNotFoundError("IPS report not found")
    report_path = safe_text(item.get("report_path"))
    report_link = f'<a href="/report-file?path={quote(report_path)}">打开 Markdown 报告</a>' if report_path else "未生成"
    round_href = (
        f"/reports/task/{html.escape(task_id)}/{html.escape(query_id)}/{round_number}"
        if task_id
        else f"/reports/{html.escape(query_id)}/{round_number}"
    )
    return report_layout(
        f"IPS {ips_id} 自动化处理详情",
        f"""<p><a href="{round_href}">返回本轮汇总</a></p>
<h1>IPS {html.escape(ips_id)} 自动化处理详情</h1>
<table><tbody>
<tr><th>关键标题</th><td>{html.escape(safe_text(item.get('title')) or '未获取')}</td></tr>
<tr><th>诊断类型</th><td>{html.escape(safe_text(item.get('diagnostic_type')))}</td></tr>
<tr><th>处理状态</th><td>{html.escape(safe_text(item.get('status')))}</td></tr>
<tr><th>是否完成测试</th><td>{'是' if item.get('test_completed') else '否'}</td></tr>
<tr><th>Owner</th><td>{html.escape(safe_text(item.get('owner')) or '未获取')}</td></tr>
<tr><th>Owner 邮件状态</th><td>{html.escape(safe_text(item.get('owner_notification_status')))}</td></tr>
<tr><th>Markdown 报告</th><td>{report_link}</td></tr>
</tbody></table>
<h2>Owner 邮件正文</h2>
<pre>{html.escape(safe_text(item.get('owner_email_body')) or '未记录')}</pre>""",
    )


class Handler(BaseHTTPRequestHandler):
    cfg: dict[str, Any] = {}

    def _send_json(self, data: Any, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_text(HTML_PAGE, content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/reports":
            self._send_text(render_report_index(), content_type="text/html; charset=utf-8")
            return
        task_report_match = re.fullmatch(r"/reports/task/([0-9a-f-]+)/(\d+)/(\d+)(?:/(\d+))?", parsed.path)
        if task_report_match:
            try:
                task_id, query_id, round_text, ips_id = task_report_match.groups()
                page = (
                    render_report_detail(query_id, int(round_text), ips_id, task_id)
                    if ips_id
                    else render_round_report(query_id, int(round_text), task_id)
                )
                self._send_text(page, content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"报告不存在或无法读取：{exc}", status=404)
            return
        report_match = re.fullmatch(r"/reports/(\d+)/(\d+)(?:/(\d+))?", parsed.path)
        if report_match:
            try:
                query_id, round_text, ips_id = report_match.groups()
                page = (
                    render_report_detail(query_id, int(round_text), ips_id)
                    if ips_id
                    else render_round_report(query_id, int(round_text))
                )
                self._send_text(page, content_type="text/html; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_text(f"报告不存在或无法读取：{exc}", status=404)
            return
        if parsed.path == "/report-file":
            try:
                report_path = safe_report_path(parse_qs(parsed.query).get("path", [""])[0])
                if not is_registered_report_path(report_path):
                    raise ValueError("report file is not registered in an automatic report")
                content = (KIT_ROOT / report_path).read_text(encoding="utf-8-sig")
                self._send_text(content, content_type="text/markdown; charset=utf-8")
            except (FileNotFoundError, OSError, ValueError) as exc:
                self._send_text(f"报告文件不存在或无法读取：{exc}", status=404)
            return
        if parsed.path == "/api/config":
            public_cfg = {
                "defaults": self.cfg.get("defaults", {}),
                "taskTypes": self.cfg.get("taskTypes", []),
                "permissionLevels": self.cfg.get("permissionLevels", []),
                "machineOptions": self.cfg.get("_machine_options", []),
                "automation": self.cfg.get("automation", {}),
                "copilotMode": self.cfg.get("copilot", {}).get("mode", "manual"),
            }
            self._send_json(public_cfg)
            return
        if parsed.path == "/api/job":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job is None:
                    self._send_json({"error": "job not found"}, status=404)
                    return
                self._send_json(job)
                return
        if parsed.path == "/api/tasks":
            if TASK_MANAGER is None:
                self._send_json({"error": "task manager is unavailable"}, status=503)
            else:
                self._send_json({"tasks": TASK_MANAGER.list()})
            return
        task_match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)", parsed.path)
        if task_match:
            task = TASK_MANAGER.get(task_match.group(1)) if TASK_MANAGER else None
            if task is None:
                self._send_json({"error": "task not found"}, status=404)
            else:
                self._send_json(task)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path in ("/api/plan-template", "/api/plan-skeleton"):
                body = self._read_json()
                self._send_json({"plan_text": initial_plan_text(body)})
                return
            if self.path == "/api/render-plan-prompt":
                body = self._read_json()
                self._send_json({"prompt": build_plan_prompt(body, self.cfg)})
                return
            if self.path == "/api/start-plan":
                body = self._read_json()
                prompt = build_plan_prompt(body, self.cfg)
                job_id = start_job("plan", prompt, self.cfg)
                self._send_json({"job_id": job_id})
                return
            if self.path == "/api/render-execute-prompt":
                body = self._read_json()
                plan_text = safe_text(body.get("plan_text"))
                permission = safe_text(body.get("permission_label"))
                task_type = safe_text(body.get("task_type"))
                auto_machine_match = bool(body.get("auto_machine_match"))
                ssh_host = safe_text(body.get("ssh_host"))
                if not plan_text:
                    raise ValueError("plan_text is required")
                self._send_json(
                    {
                        "prompt": build_execute_prompt(
                            plan_text,
                            self.cfg,
                            permission,
                            task_type,
                            auto_machine_match,
                            ssh_host,
                        )
                    }
                )
                return
            if self.path == "/api/start-execute":
                body = self._read_json()
                plan_text = safe_text(body.get("plan_text"))
                permission = safe_text(body.get("permission_label"))
                task_type = safe_text(body.get("task_type"))
                auto_machine_match = bool(body.get("auto_machine_match"))
                ssh_host = safe_text(body.get("ssh_host"))
                if not plan_text:
                    raise ValueError("plan_text is required")
                prompt = build_execute_prompt(
                    plan_text,
                    self.cfg,
                    permission,
                    task_type,
                    auto_machine_match,
                    ssh_host,
                )
                job_id = start_job("execute", prompt, self.cfg)
                self._send_json({"job_id": job_id})
                return
            if self.path == "/api/tasks":
                body = self._read_json()
                query_id = safe_text(body.get("query_id"))
                interval_minutes = int(body.get("interval_minutes"))
                manager_recipients = safe_text(body.get("manager_recipients"))
                creator_name = safe_text(body.get("creator_name"))
                if TASK_MANAGER is None:
                    raise RuntimeError("task manager is unavailable")
                self._send_json(TASK_MANAGER.start(query_id, creator_name, interval_minutes, manager_recipients))
                return
            cancel_match = re.fullmatch(r"/api/tasks/([0-9a-f-]+)/cancel", self.path)
            if cancel_match:
                body = self._read_json()
                if TASK_MANAGER is None:
                    raise RuntimeError("task manager is unavailable")
                self._send_json(TASK_MANAGER.cancel(cancel_match.group(1), safe_text(body.get("reason"))))
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=400)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def task_lock_command(cfg: dict[str, Any], task_id: str, machine_id: str, action: str, wait: bool) -> int:
    inventory_path = pathlib.Path(cfg.get("machineMatching", {}).get("inventoryPath", "config\\lab-machine-inventory.json"))
    if not inventory_path.is_absolute():
        inventory_path = KIT_ROOT / inventory_path
    try:
        inventory = read_json(inventory_path)
        registered_machine_ids = {safe_text(machine.get("id")) for machine in inventory.get("machines", []) if isinstance(machine, dict)}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MACHINE_LOCK_INVENTORY_ERROR={type(exc).__name__}: {exc}")
        return 2
    if machine_id not in registered_machine_ids:
        print(f"MACHINE_LOCK_UNKNOWN_MACHINE={machine_id}")
        return 2
    automation = cfg.get("automation", {})
    database_path = pathlib.Path(automation.get("taskDatabasePath", "out\\ui_task_manager.sqlite3"))
    if not database_path.is_absolute():
        database_path = KIT_ROOT / database_path
    store = TaskStore(database_path, automation.get("perMachineConcurrency", {"default": 1}), recover_active=False)
    if action == "release":
        store.release_machine(task_id, machine_id)
        print(f"MACHINE_LOCK_RELEASED={machine_id}")
        return 0
    deadline = time.time() + int(automation.get("machineLockWaitSeconds", 3600)) if wait else time.time()
    while True:
        task = store.get_task(task_id)
        if task and task["status"] in ("cancelling", "cancelled", "interrupted"):
            print("MACHINE_LOCK_CANCELLED")
            return 2
        if store.try_acquire_machine(task_id, machine_id):
            if task and task["status"] == "waiting_resource":
                store.update(task_id, status="running")
            print(f"MACHINE_LOCK_ACQUIRED={machine_id}")
            return 0
        if task and task["status"] == "running":
            store.update(task_id, status="waiting_resource")
        if not wait or time.time() >= deadline:
            print(f"MACHINE_LOCK_UNAVAILABLE={machine_id}")
            return 75
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start portable IPS/HSD Copilot UI.")
    parser.add_argument("--config", default=str(KIT_ROOT / "config" / "ips-copilot-ui.template.json"))
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--copilot-mode", choices=["manual", "subprocess"])
    parser.add_argument("--task-lock", action="store_true", help="Acquire or release a persisted hardware machine reservation.")
    parser.add_argument("--task-id")
    parser.add_argument("--machine-id")
    parser.add_argument("--action", choices=["acquire", "release"])
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()

    cfg_path = pathlib.Path(args.config).resolve()
    cfg = load_config(cfg_path)
    cfg["_machine_options"] = load_machine_options(cfg)
    if args.host:
        deep_set(cfg, "server.host", args.host)
    if args.port:
        deep_set(cfg, "server.port", args.port)
    if args.no_browser:
        deep_set(cfg, "server.openBrowser", False)
    if args.copilot_mode:
        deep_set(cfg, "copilot.mode", args.copilot_mode)
    if args.task_lock:
        if not args.task_id or not args.machine_id or not args.action:
            parser.error("--task-lock requires --task-id, --machine-id, and --action")
        return task_lock_command(cfg, args.task_id, args.machine_id, args.action, args.wait)

    host = cfg.get("server", {}).get("host", "127.0.0.1")
    port = int(cfg.get("server", {}).get("port", 8765))
    Handler.cfg = cfg
    global TASK_MANAGER
    TASK_MANAGER = TaskManager(cfg)

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"IPS/HSD Copilot UI started: {url}")
    print(f"Config: {cfg_path}")
    print(f"Copilot mode: {cfg.get('copilot', {}).get('mode', 'manual')}")
    print("Press Ctrl+C to stop.")
    if cfg.get("server", {}).get("openBrowser", True):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping UI.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
