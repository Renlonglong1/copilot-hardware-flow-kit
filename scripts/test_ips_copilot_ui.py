"""Focused stdlib tests for persistent Query task management."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).with_name("ips_copilot_ui.py")
SPEC = importlib.util.spec_from_file_location("ips_copilot_ui", SCRIPT)
assert SPEC and SPEC.loader
ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ui)


class TaskManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = pathlib.Path(__file__).resolve().parents[1] / "out" / "ui_task_manager_unittest"
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True)
        self.database = self.work / "tasks.sqlite3"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def test_sqlite_lifecycle_restart_cancellation_and_machine_lock(self) -> None:
        store = ui.TaskStore(self.database, {"default": 1})
        first = store.create_task("100", "Alice", 60, "", "")
        queued = store.request_cancel(first["id"], "not needed")
        self.assertEqual("cancelled", queued["status"])
        self.assertEqual("not needed", queued["cancellation_reason"])

        running = store.create_task("101", "Bob", 60, "", "")
        store.update(running["id"], status="running")
        self.assertTrue(store.try_acquire_machine(running["id"], "lab-control-05"))
        self.assertFalse(store.try_acquire_machine("other-task", "lab-control-05"))

        restarted = ui.TaskStore(self.database, {"default": 1})
        self.assertEqual("interrupted", restarted.get_task(running["id"])["status"])
        self.assertIn("restarted", restarted.get_task(running["id"])["cancellation_reason"])
        self.assertFalse(restarted.try_acquire_machine("other-task", "lab-control-05"))
        restarted.release_machine(running["id"], "lab-control-05")
        self.assertTrue(restarted.try_acquire_machine("other-task", "lab-control-05"))

    def test_report_only_task_runs_once_without_open_ips_execution(self) -> None:
        previous_reports = ui.AUTO_REPORTS_DIR
        ui.AUTO_REPORTS_DIR = self.work / "reports"
        manager = ui.TaskManager(
            {
                "automation": {
                    "taskDatabasePath": str(self.database),
                    "perMachineConcurrency": {"default": 1},
                    "retentionDays": 0,
                },
                "copilot": {"mode": "subprocess", "stage2Mode": "subprocess"},
            }
        )
        try:
            task = manager.store.create_task("102", "Alice", 0, "manager@example.test", "http://reports.example.test", report_only=True)
            analysis = {"recommended_count": 1, "recommendations": []}
            fetch_summary = {"requested": 1, "fetched": 1, "failed": 0, "sighting_requested": 0, "sighting_fetched": 0, "sighting_failed": 0, "limitation": ""}
            with (
                mock.patch.object(ui, "execute_hsd_query", return_value=[{"id": "900", "status": "open"}]),
                mock.patch.object(ui, "enrich_auto_query_article_rows", return_value=([{"id": "900"}], fetch_summary)),
                mock.patch.object(ui, "build_auto_query_common_issue_analysis", return_value=analysis),
                mock.patch.object(ui, "build_auto_execute_prompt", side_effect=AssertionError("Open IPS execution must be skipped")),
                mock.patch.object(ui, "send_round_notification") as notification,
            ):
                manager._worker(task["id"], ui.threading.Event())
            completed = manager.store.get_task(task["id"])
            self.assertEqual("completed", completed["status"])
            self.assertEqual(1, completed["current_round"])
            self.assertTrue(completed["report_only"])
            report = ui.load_auto_round("102", 1, task["id"])
            self.assertEqual([], report["items"])
            notification.assert_called_once()
            self.assertEqual(("manager@example.test", "http://reports.example.test"), notification.call_args[0][1:])
        finally:
            ui.AUTO_REPORTS_DIR = previous_reports

    def test_report_index_groups_same_query_by_task(self) -> None:
        previous = ui.AUTO_REPORTS_DIR
        ui.AUTO_REPORTS_DIR = self.work / "reports"
        try:
            for task_id in ("task-a", "task-b"):
                ui.write_auto_round(
                    {
                        "task_id": task_id,
                        "query_id": "200",
                        "round": 1,
                        "started_at": "2026-01-01T00:00:00",
                        "completed_at": "2026-01-01T00:01:00",
                        "status": "completed",
                        "items": [],
                    }
                )
            records = ui.list_auto_rounds()
            self.assertEqual({"task-a", "task-b"}, {record["task_id"] for record in records})
            page = ui.render_report_index()
            self.assertIn("/reports/task/task-a/200/1", page)
            self.assertIn("/reports/task/task-b/200/1", page)
            self.assertIn("/reports/task/task-a/200/1/top-ips", page)
        finally:
            ui.AUTO_REPORTS_DIR = previous

    def test_top_ips_report_is_separate_from_query_execution_report(self) -> None:
        previous = ui.AUTO_REPORTS_DIR
        ui.AUTO_REPORTS_DIR = self.work / "reports"
        try:
            ui.write_auto_round(
                {
                    "task_id": "task-a",
                    "query_id": "200",
                    "round": 1,
                    "started_at": "2026-01-01T00:00:00",
                    "completed_at": "2026-01-01T00:01:00",
                    "status": "completed",
                    "items": [],
                    "common_issue_analysis": {
                        "recommendations": [{
                            "ips_id": "10", "reference_score": 90, "summary": "Memory training timeout",
                            "reuse_reason": "Known workaround.", "applicability": "BHS", "limitations": "",
                            "record": {"title": "Memory training", "query_status": "closed", "hsd_url": ""},
                        }],
                    },
                }
            )
            round_page = ui.render_round_report("200", 1, "task-a")
            top_page = ui.render_top_ips_report("200", 1, "task-a")
            self.assertIn("打开 Top IPS 参考报告", round_page)
            self.assertNotIn("Memory training timeout", round_page)
            self.assertIn("Top IPS Reference Report", top_page)
            self.assertIn('lang="en"', top_page)
            self.assertIn("Memory training timeout", top_page)
        finally:
            ui.AUTO_REPORTS_DIR = previous

    def test_report_index_includes_manual_execution_reports(self) -> None:
        previous = ui.MANUAL_REPORTS_DIR
        ui.MANUAL_REPORTS_DIR = self.work / "manual_reports"
        try:
            ui.write_manual_report(
                {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "ips_id": "14025984558",
                    "task_type": "consult",
                    "ui_mode": "simple",
                    "recipient": "recipient@example.test",
                    "plan_text": "test plan",
                    "status": "completed",
                    "created_at": 1,
                    "completed_at": 2,
                    "exit_code": 0,
                    "output": "completed",
                }
            )
            page = ui.render_report_index()
            self.assertIn("简洁模式", page)
            self.assertIn("/reports/manual/123e4567-e89b-12d3-a456-426614174000", page)
            report = ui.render_manual_report("123e4567-e89b-12d3-a456-426614174000")
            self.assertIn('href="mailto:recipient@example.test"', report)
        finally:
            ui.MANUAL_REPORTS_DIR = previous

    def test_task_center_combines_manual_and_query_records(self) -> None:
        previous_reports = ui.MANUAL_REPORTS_DIR
        previous_manager = ui.TASK_MANAGER
        ui.MANUAL_REPORTS_DIR = self.work / "manual_reports"
        ui.write_manual_report(
            {
                "id": "manual-task",
                "ips_id": "14025984558",
                "task_type": "consult",
                "ui_mode": "simple",
                "submitted_by": "Alice",
                "status": "running",
                "created_at": 10,
                "completed_at": 0,
            }
        )

        class Manager:
            def list(self):
                return [{
                    "id": "query-task", "query_id": "200", "creator_name": "Bob",
                    "status": "queued", "created_at": 20, "completed_at": 0,
                    "current_round": 2, "current_ips_id": "300", "report_only": False,
                }]

        ui.TASK_MANAGER = Manager()
        try:
            records = ui.list_task_center_records()
            self.assertEqual(["query", "manual"], [record["source"] for record in records])
            manual = records[1]
            self.assertEqual("简洁模式", manual["mode"])
            self.assertEqual("Alice", manual["submitter"])
            self.assertEqual("/reports/manual/manual-task", manual["detail_href"])
            self.assertEqual("第 2 轮 · 当前 IPS 300", records[0]["progress"])
        finally:
            ui.MANUAL_REPORTS_DIR = previous_reports
            ui.TASK_MANAGER = previous_manager

    def test_report_time_and_recipient_links_are_human_readable(self) -> None:
        self.assertEqual("2026-08-12 13:43:14", ui.format_task_time("2026-08-12T13:43:14+0800"))
        self.assertEqual("2026-08-12 13:43:14", ui.format_task_time("2026-08-12T13:43:14Z"))
        links = ui.recipient_email_links("owner@example.test; manager@example.test")
        self.assertIn('href="mailto:owner@example.test"', links)
        self.assertIn('href="mailto:manager@example.test"', links)
        self.assertNotIn("mailto:", ui.recipient_email_links("Outlook Display Name"))

    def test_plan_uses_specified_recipient_and_standard_report_directory(self) -> None:
        plan = ui.initial_plan_text(
            {
                "ips_id": "14025984558",
                "task_type": "consult",
                "notification_recipient": "recipient@example.test",
                "output_dir": "ignored",
            }
        )
        self.assertIn("发送用户：recipient@example.test", plan)
        self.assertIn("out\\14025984558", plan)
        self.assertNotIn("ignored", plan)

    def test_local_ui_config_inherits_template_option_lists(self) -> None:
        local_config = self.work / "ips-copilot-ui.json"
        local_config.write_text(
            json.dumps({"server": {"host": "192.0.2.1", "port": 8765}}),
            encoding="utf-8",
        )
        config = ui.load_config(local_config)
        self.assertEqual("192.0.2.1", config["server"]["host"])
        self.assertTrue(config["taskTypes"])
        self.assertTrue(config["permissionLevels"])

    def test_execute_prompt_requests_deep_report_and_link(self) -> None:
        prompt = ui.build_execute_prompt(
            "final plan",
            {},
            task_type="consult",
            report_base_url="http://ui.example.test:8765",
        )
        self.assertIn("http://ui.example.test:8765/reports/manual/{manual_report_id}", prompt)
        self.assertIn("customer_information_needed", prompt)
        self.assertIn("out\\manual_reports\\{manual_report_id}.summary.json", prompt)

    def test_debug_prompt_requires_post_match_resource_request_draft(self) -> None:
        prompt = ui.build_execute_prompt(
            "final plan",
            {},
            task_type="debug_repro",
        )
        self.assertIn("在提取 IPS/HSD、客户环境与测试诉求，并依据机器库存完成兼容性比对后、执行任何硬件动作前", prompt)
        self.assertIn("resource_request_draft.md", prompt)
        self.assertIn("期望 DDL：<MANUAL_DDL>", prompt)
        self.assertIn("预计占用：<MANUAL_RESOURCE>", prompt)
        self.assertIn("预计时长：<MANUAL_DURATION>", prompt)
        self.assertIn('"resource_request_status":"needed|not_needed|blocked|not_applicable"', prompt)

    def test_report_center_summary_renders_diagnostic_sections(self) -> None:
        page = ui.render_report_center_summary(
            {
                "problem_analysis": "memory training failure",
                "diagnostic_results": "reproduced with evidence",
                "next_steps": ["collect firmware log"],
                "customer_information_needed": ["BIOS version"],
                "risks_and_limitations": "not reproduced on another platform",
            }
        )
        self.assertIn("详细诊断结果", page)
        self.assertIn("客户待补充信息", page)
        self.assertIn("BIOS version", page)

    def test_manager_draft_renders_headings_lists_and_resource_table(self) -> None:
        rendered = ui.render_manager_draft(
            "# 资源申请与排期协调\n\n## 管理摘要\n- 客户需要验证\n\n## 需协调的资源\n| 类别 | 需求 |\n| --- | --- |\n| 平台 | OKS |\n"
        )
        self.assertIn("<h1>资源申请与排期协调</h1>", rendered)
        self.assertIn("<li>客户需要验证</li>", rendered)
        self.assertIn("<th>类别</th>", rendered)
        self.assertIn("<td>OKS</td>", rendered)

    def test_resource_request_details_can_be_updated_and_email_is_concise(self) -> None:
        previous_root = ui.KIT_ROOT
        previous_reports = ui.MANUAL_REPORTS_DIR
        ui.KIT_ROOT = self.work
        ui.MANUAL_REPORTS_DIR = self.work / "out" / "manual_reports"
        draft_path = self.work / "out" / "10" / "resource_request_draft.md"
        draft_path.parent.mkdir(parents=True)
        draft_path.write_text(
            "# 资源协调申请\n\n期望 DDL：<MANUAL_DDL>\n预计占用：<MANUAL_RESOURCE>\n预计时长：<MANUAL_DURATION>\n",
            encoding="utf-8",
        )
        ui.MANUAL_REPORTS_DIR.mkdir(parents=True)
        ui.write_manual_report({
            "id": "job-1",
            "ips_id": "10",
            "report_center_summary": {"resource_request_path": "out\\10\\resource_request_draft.md"},
        })
        try:
            ui.save_resource_request_details("job-1", "2026-09-15", "BHS server", "2 days", "manager@example.test")
            ui.save_resource_request_details("job-1", "2026-09-16", "BHS server and serial", "3 days", "manager@example.test")
            record = ui.load_manual_report("job-1")
            subject, body = ui.resource_request_email_content(record, "http://reports/request")
            self.assertIn("2026-09-16", draft_path.read_text(encoding="utf-8"))
            self.assertIn("资源协调申请", subject)
            self.assertIn("- 所需资源：BHS server and serial", body)
            self.assertIn("- 期望时间：2026-09-16", body)
            self.assertNotIn("根因", body)
            self.assertLess(len(body), 300)
        finally:
            ui.KIT_ROOT = previous_root
            ui.MANUAL_REPORTS_DIR = previous_reports

    def test_manual_debug_report_requires_summary_and_resource_draft(self) -> None:
        previous_root = ui.KIT_ROOT
        ui.KIT_ROOT = self.work
        try:
            report = {
                "id": "job-artifact",
                "task_type": "debug_repro",
                "summary_path": "out\\manual_reports\\job-artifact.summary.json",
            }
            self.assertIn("未生成", ui.manual_report_artifact_error(report))

            draft_path = self.work / "out" / "10" / "resource_request_draft.md"
            draft_path.parent.mkdir(parents=True)
            draft_path.write_text("# 资源协调申请\n", encoding="utf-8")
            ui.write_json(
                self.work / "out" / "manual_reports" / "job-artifact.summary.json",
                {
                    "problem_analysis": "memory training issue",
                    "diagnostic_results": "blocked before validation",
                    "resource_request_path": "out\\10\\resource_request_draft.md",
                },
            )
            self.assertEqual("", ui.manual_report_artifact_error(report))
        finally:
            ui.KIT_ROOT = previous_root

    def test_resource_draft_notification_is_deferred_to_ui_completion(self) -> None:
        prompt = ui.build_execute_prompt("plan", {}, task_type="debug_repro")
        self.assertIn("不得自行发送通知", prompt)
        self.assertIn("UI 会在摘要与草稿路径持久化并可访问后", prompt)

        report = {"task_type": "debug_repro", "recipient": ""}
        ui.send_resource_draft_notification(report)
        self.assertEqual("not_requested", report["resource_request_notification_status"])

    def test_ui_dispatch_feedback_and_resource_review_use_explicit_controls(self) -> None:
        self.assertIn('id="dispatchNotice"', ui.HTML_PAGE)
        self.assertIn('function showDispatchNotice(', ui.HTML_PAGE)
        self.assertIn('id="autoStartButton"', ui.HTML_PAGE)
        self.assertIn('id="executeButton"', ui.HTML_PAGE)
        self.assertIn('id="submittedBy"', ui.HTML_PAGE)
        self.assertIn("请填写任务下发人。", ui.HTML_PAGE)
        self.assertIn('setActionBusy("simpleStartButton", true, "正在下发任务…")', ui.HTML_PAGE)

        previous_root = ui.KIT_ROOT
        previous_reports = ui.MANUAL_REPORTS_DIR
        ui.KIT_ROOT = self.work
        ui.MANUAL_REPORTS_DIR = self.work / "out" / "manual_reports"
        draft_path = self.work / "out" / "10" / "resource_request_draft.md"
        draft_path.parent.mkdir(parents=True)
        draft_path.write_text("# 资源协调申请\n\n期望 DDL：<MANUAL_DDL>\n预计占用：<MANUAL_RESOURCE>\n预计时长：<MANUAL_DURATION>\n", encoding="utf-8")
        ui.write_manual_report({
            "id": "job-2",
            "ips_id": "10",
            "resource_request_recipient": "manager@example.test",
            "report_center_summary": {"resource_request_path": "out\\10\\resource_request_draft.md"},
        })
        try:
            page = ui.render_resource_request_review("job-2")
            self.assertIn('type="button" onclick="saveDetails()"', page)
            self.assertIn("function reviewElements()", page)
            self.assertIn('document.getElementById("saveButton")', page)
            self.assertIn('document.getElementById("sendButton")', page)
        finally:
            ui.KIT_ROOT = previous_root
            ui.MANUAL_REPORTS_DIR = previous_reports

    def test_task_api_posts_without_external_services(self) -> None:
        class Manager:
            def __init__(self) -> None:
                self.started = None
                self.cancelled = None

            def start(self, query_id, creator_name, interval_minutes, manager_recipients, report_only=False):
                self.started = (query_id, creator_name, interval_minutes, manager_recipients, report_only)
                return {"id": "123e4567-e89b-12d3-a456-426614174000", "status": "queued"}

            def cancel(self, task_id, reason):
                self.cancelled = (task_id, reason)
                return {"id": task_id, "status": "cancelled", "cancellation_reason": reason}

            def list(self):
                return [{"id": "123e4567-e89b-12d3-a456-426614174000", "status": "queued"}]

        manager = Manager()
        previous = ui.TASK_MANAGER
        ui.TASK_MANAGER = manager
        try:
            handler = object.__new__(ui.Handler)
            response = {}
            handler.cfg = {}
            handler.path = "/api/tasks"
            handler._read_json = lambda: {
                "query_id": "300",
                "creator_name": "Carol",
                "interval_minutes": 60,
                "manager_recipients": "manager@example.test",
            }
            handler._send_json = lambda data, status=200: response.update(data=data, status=status)
            handler.do_POST()
            self.assertEqual(("300", "Carol", 60, "manager@example.test", False), manager.started)
            task_id = "123e4567-e89b-12d3-a456-426614174000"
            self.assertEqual(task_id, response["data"]["id"])

            handler.path = "/api/tasks"
            handler._read_json = lambda: {
                "query_id": "301",
                "creator_name": "Carol",
                "report_only": True,
            }
            handler.do_POST()
            self.assertEqual(("301", "Carol", 0, "", True), manager.started)

            handler.path = f"/api/tasks/{task_id}/cancel"
            handler._read_json = lambda: {"reason": "user stopped it"}
            handler.do_POST()
            self.assertEqual((task_id, "user stopped it"), manager.cancelled)
            self.assertEqual("cancelled", response["data"]["status"])

            handler.path = "/api/tasks"
            handler.do_GET()
            self.assertEqual("queued", response["data"]["tasks"][0]["status"])

            handler.path = "/api/task-center"
            with mock.patch.object(ui, "list_task_center_records", return_value=[{"id": "manual-task"}]):
                handler.do_GET()
            self.assertEqual([{"id": "manual-task"}], response["data"]["tasks"])
        finally:
            ui.TASK_MANAGER = previous

    def test_cancellation_terminates_process_before_kill(self) -> None:
        class FakeProcess:
            pid = 42

            def __init__(self) -> None:
                self.terminated = False
                self.killed = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def send_signal(self, _signal):
                self.terminated = True

            def wait(self, timeout):
                return 0

            def kill(self):
                self.killed = True

        manager = ui.TaskManager(
            {
                "automation": {
                    "taskDatabasePath": str(self.database),
                    "cancellationGraceSeconds": 1,
                    "perMachineConcurrency": {"default": 1},
                    "retentionDays": 0,
                }
            }
        )
        proc = FakeProcess()
        manager._terminate_process(proc)
        self.assertTrue(proc.terminated)
        self.assertFalse(proc.killed)

    def test_duplicate_active_query_is_rejected_before_worker_starts(self) -> None:
        manager = ui.TaskManager(
            {
                "automation": {
                    "taskDatabasePath": str(self.database),
                    "perMachineConcurrency": {"default": 1},
                    "retentionDays": 0,
                },
                "copilot": {"mode": "subprocess", "stage2Mode": "subprocess"},
            }
        )
        existing = {
            "id": "existing-task",
            "query_id": "300",
            "creator_name": "Alice",
            "status": "running",
        }
        manager.store.find_active_query = lambda query_id: existing if query_id == "300" else None
        with self.assertRaises(ui.DuplicateQueryTaskError) as raised:
            manager.start("300", "Bob", 60, "")
        self.assertEqual(existing, raised.exception.task)

    def test_common_issue_filter_validation_dates_and_limits(self) -> None:
        cfg = {
            "commonIssueAnalysis": {
                "maxDateRangeDays": 7,
                "defaultResultLimit": 5,
                "maxResultLimit": 10,
            }
        }
        filters = ui.validate_common_issue_filters(
            {
                "platform": "BHS",
                "customer": "",
                "submitted_start_date": "2026-01-01",
                "submitted_end_date": "2026-01-08",
                "component": "",
                "keywords": "",
                "result_limit": "",
            },
            cfg,
        )
        self.assertEqual(5, filters.result_limit)
        with self.assertRaises(ValueError):
            ui.validate_common_issue_filters(
                {"submitted_start_date": "2026-01-01", "submitted_end_date": "2026-01-02"},
                cfg,
            )
        with self.assertRaises(ValueError):
            ui.validate_common_issue_filters(
                {"platform": "BHS", "submitted_start_date": "2026-02-30", "submitted_end_date": "2026-03-01"},
                cfg,
            )
        with self.assertRaises(ValueError):
            ui.validate_common_issue_filters(
                {"platform": "BHS", "submitted_start_date": "2026-01-08", "submitted_end_date": "2026-01-01"},
                cfg,
            )
        with self.assertRaises(ValueError):
            ui.validate_common_issue_filters(
                {"platform": "BHS", "submitted_start_date": "2026-01-01", "submitted_end_date": "2026-01-09", "result_limit": 11},
                cfg,
            )
        with self.assertRaises(ValueError):
            ui.common_issue_config({"commonIssueAnalysis": {"autoQueryArticleFetchConcurrency": "invalid"}})

    def test_common_issue_normalization_sighting_candidates(self) -> None:
        normalized = ui.normalize_common_issue_row(
            {
                "id": "14025984558",
                "title": "Memory initialization fails",
                "platform_name": "BHS",
                "component_name": "Memory",
                "submitted_date": "2026-01-02T12:00:00Z",
                "tenant": {"customer": "Example Customer", "in_sighting": "14025000000"},
            }
        )
        self.assertEqual("BHS", normalized["platform"])
        self.assertEqual("Example Customer", normalized["customer"])
        self.assertTrue(normalized["sighting_verified"])
        self.assertIn("14025000000", normalized["sighting_url"])
        self.assertEqual("https://hsdes.intel.com/appstore/article_legacy/#/14025984558", normalized["hsd_url"])

        missing = ui.normalize_common_issue_row({"id": "1", "in_sighting": "not a sighting"})
        self.assertFalse(missing["sighting_verified"])
        self.assertEqual("", missing["sighting_url"])

    def test_common_issue_prefers_customer_company(self) -> None:
        normalized = ui.normalize_common_issue_row(
            {
                "id": "14025984558",
                "customer_company": "Example Customer Company",
                "customer": "Internal account alias",
            }
        )
        self.assertEqual("Example Customer Company", normalized["customer"])

    def test_common_issue_extracts_verified_reuse_fields_and_strips_html(self) -> None:
        normalized = ui.normalize_common_issue_row(
            {
                "id": "14028413197",
                "description": "<p>Multiple systems report IERR after cold boot.</p><style>.noise{font-size:16px}</style>",
                "release": "Birch Stream Platform GNR SP",
                "priority": "P1",
                "server_platf_ae": {
                    "bug": {
                        "article_type": "debug_request",
                        "customer_project_name": "Example GNR Project",
                        "conclusion_type": "intel",
                        "close_reason": "internal_fixed",
                        "fix_description": "<p>Upgrade BKC and collect serial log.</p>",
                        "ext_cust_blog_hist": "<p>Customer reproduced the IERR on three systems.</p>",
                    }
                },
            }
        )
        self.assertEqual("debug", normalized["ips_type"])
        self.assertEqual("Multiple systems report IERR after cold boot.", normalized["customer_description"])
        self.assertEqual("Example GNR Project", normalized["customer_project_name"])
        self.assertEqual("Birch Stream Platform GNR SP", normalized["release"])
        self.assertEqual("P1", normalized["priority"])
        self.assertEqual("intel", normalized["conclusion_type"])
        self.assertEqual("internal_fixed", normalized["close_reason"])
        self.assertIn("Fix/workaround: Upgrade BKC and collect serial log.", normalized["analysis_text"])
        self.assertIn("Customer history: Customer reproduced the IERR on three systems.", normalized["analysis_text"])
        self.assertNotIn("16px", normalized["analysis_text"])
        cleaned_comments = ui.clean_hsd_text(
            "++++123 sys_voc Routing rules applied: metadata ++++456 engineer Useful engineer conclusion."
        )
        self.assertNotIn("Routing rules", cleaned_comments)
        self.assertIn("Useful engineer conclusion.", cleaned_comments)

    def test_common_issue_keywords_exclude_ids_years_and_css_artifacts(self) -> None:
        tokens = ui._title_tokens("DDR training timeout 1407520027 2023 16px https://hsdes.intel.com")
        self.assertIn("ddr", tokens)
        self.assertIn("training", tokens)
        self.assertNotIn("1407520027", tokens)
        self.assertNotIn("2023", tokens)
        self.assertNotIn("16px", tokens)
        self.assertNotIn("https", tokens)

    def test_common_issue_normalizes_equivalent_sighting_urls(self) -> None:
        first = ui.normalize_common_issue_row(
            {"id": "1", "in_sighting": {"url": "https://HSDES.INTEL.COM/appstore/article_legacy/#/14025000000?view=full"}}
        )
        second = ui.normalize_common_issue_row(
            {"id": "2", "in_sighting": {"url": "https://hsdes.intel.com/appstore/article_legacy/#/14025000000"}}
        )
        self.assertEqual("14025000000", first["sighting_reference"])
        self.assertEqual(first["sighting_reference"], second["sighting_reference"])
        groups = ui.build_common_issue_groups([first, second])
        self.assertEqual("强证据", groups[0]["evidence_tier"])
        self.assertEqual(100, groups[0]["confidence_score"])
        self.assertIn("共同已验证 SI/FW sighting", groups[0]["evidence_signals"][0])

    def test_common_issue_extracts_html_int_sighting_and_bug_closed_reason(self) -> None:
        normalized = ui.normalize_common_issue_row(
            {
                "id": "1",
                "server_platf_ae.bug.int_sighting_url": (
                    '<?xml version="1.0"?><dict><a href="https://hsdes.intel.com/appstore/article/#/15014989677">'
                    "https://hsdes.intel.com/appstore/article/#/15014989677</a></dict>"
                ),
                "bug.closed_reason": "internal_fixed",
            }
        )
        self.assertEqual("https://hsdes.intel.com/appstore/article/#/15014989677", normalized["sighting_url"])
        self.assertEqual("15014989677", normalized["sighting_reference"])
        self.assertEqual("internal_fixed", normalized["close_reason"])

    def test_common_issue_normalizes_end_date(self) -> None:
        normalized = ui.normalize_common_issue_row({"id": "1", "end_date": "2026-08-20T12:00:00Z"})
        self.assertEqual("2026-08-20", normalized["closed_date"])

    def test_common_issue_uses_int_sighting_and_excludes_question_only_groups(self) -> None:
        debug = ui.normalize_common_issue_row(
            {
                "id": "1", "issue_type": "Debug",
                "server_platf_ae": {"bug": {"int_sighting_url": "https://hsdes.intel.com/appstore/article_legacy/#/14025000000"}},
            }
        )
        question = ui.normalize_common_issue_row(
            {
                "id": "2", "issue_type": "Question",
                "server_platf_ae": {"bug": {"int_sighting_url": "https://hsdes.intel.com/appstore/article_legacy/#/14025000000"}},
            }
        )
        self.assertEqual("debug", debug["ips_type"])
        self.assertEqual("question", question["ips_type"])
        groups = ui.build_common_issue_groups([debug, question])
        self.assertEqual(1, len(groups))
        self.assertEqual("强证据", groups[0]["evidence_tier"])
        self.assertEqual(1, groups[0]["debug_count"])
        self.assertEqual(1, groups[0]["question_count"])
        question_groups = ui.build_common_issue_groups([
            {"ips_id": "3", "ips_type": "question", "sighting_verified": True, "sighting_reference": "99"},
            {"ips_id": "4", "ips_type": "question", "sighting_verified": True, "sighting_reference": "99"},
        ])
        self.assertEqual(1, len(question_groups))
        self.assertEqual("强证据", question_groups[0]["evidence_tier"])

    def test_common_issue_groups_distinct_int_sightings_as_association(self) -> None:
        groups = ui.build_common_issue_groups([
            {
                "ips_id": "1", "ips_type": "debug", "sighting_verified": True,
                "sighting_reference": "101", "sighting_source_field": "int_sighting_url",
            },
            {
                "ips_id": "2", "ips_type": "debug", "sighting_verified": True,
                "sighting_reference": "202", "sighting_source_field": "server_platf_ae.bug.int_sighting_url",
            },
        ])
        self.assertEqual(1, len(groups))
        self.assertEqual("有 int_sighting_url 的 IPS", groups[0]["heading"])
        self.assertEqual("关联证据", groups[0]["evidence_tier"])
        self.assertIn("不同链接", groups[0]["common_problem_explanation"])

    def test_invalid_ai_association_uses_candidate_evidence_signals(self) -> None:
        issues = [
            {"ips_id": "1", "description": "same boot failure"},
            {"ips_id": "2", "description": "same boot failure"},
        ]
        value = {
            "groups": [{
                "heading": "Boot failure",
                "common_problem_explanation": "Both reports describe the same boot failure.",
                "evidence_tier": "关联证据",
                "ips_ids": ["1", "2"],
                "grouping_reason": "The reported failure signature is the same.",
            }],
        }
        groups = ui.validate_ai_common_issue_groups(value, issues)
        self.assertEqual("候选证据", groups[0]["evidence_tier"])
        self.assertNotIn("int_sighting_url", groups[0]["evidence_signals"][0])

    def test_ai_groups_preserve_distinct_int_sighting_association(self) -> None:
        issues = [
            {
                "ips_id": "1", "ips_type": "debug", "sighting_verified": True,
                "sighting_reference": "101", "sighting_source_field": "int_sighting_url",
            },
            {
                "ips_id": "2", "ips_type": "debug", "sighting_verified": True,
                "sighting_reference": "202", "sighting_source_field": "int_sighting_url",
            },
            {"ips_id": "3", "ips_type": "debug", "description": "Same cold boot timeout"},
        ]
        ai_groups = [{
            "heading": "AI content category",
            "evidence_tier": "候选证据",
            "grouping_key": "ai|1|2|3",
            "records": [{"ips_id": "1"}, {"ips_id": "2"}, {"ips_id": "3"}],
        }]
        enforced = ui.enforce_int_sighting_association_group(ai_groups, issues)
        self.assertEqual("有 int_sighting_url 的 IPS", enforced[-1]["heading"])
        self.assertEqual({"1", "2"}, ui.grouped_common_issue_ids([enforced[-1]]))
        self.assertFalse(any(group["grouping_key"] == "ai|1|2|3" for group in enforced))

    def test_common_issue_deterministic_groups_and_strict_ai_rejection(self) -> None:
        issues = [
            {"ips_id": "1", "title": "Memory training failure", "platform": "BHS", "component": "Memory", "sighting_reference": "99", "sighting_title": "Shared FW issue", "sighting_verified": True},
            {"ips_id": "2", "title": "Memory training failure", "platform": "BHS", "component": "Memory", "sighting_reference": "99", "sighting_title": "Shared FW issue", "sighting_verified": True},
            {"ips_id": "3", "title": "PCIe link retry", "platform": "BHS", "component": "PCIe", "sighting_reference": "", "sighting_verified": False},
        ]
        groups = ui.build_common_issue_groups(issues)
        strong = next(group for group in groups if group["evidence_tier"] == "强证据")
        self.assertIn("共同 SI/FW Sighting", strong["heading"])
        self.assertEqual(["1", "2"], [record["ips_id"] for record in strong["records"]])
        self.assertIn("共同 sighting", strong["records"][0]["grouping_reason"])

        rejected = ui.validate_ai_common_issue_groups(
            {"groups": [{"heading": "bad", "common_problem_explanation": "bad", "evidence_tier": "强证据", "ips_ids": ["unknown"], "grouping_reason": "bad"}]},
            issues,
        )
        self.assertEqual(groups, rejected)

    def test_common_issue_groups_filter_singletons_and_accept_broad_ai_group(self) -> None:
        issues = [
            {"ips_id": "1", "title": "Memory training fails on cold boot", "description": "DDR memory training error", "analysis_text": "Description: DDR memory training error"},
            {"ips_id": "2", "title": "Memory initialization failure", "description": "DDR memory training error", "analysis_text": "Description: DDR memory training error"},
            {"ips_id": "3", "title": "Unrelated PCIe question", "description": "A unique question", "analysis_text": "Description: A unique question"},
        ]
        deterministic = ui.build_common_issue_groups(issues)
        self.assertEqual(1, len(deterministic))
        self.assertEqual({"1", "2"}, ui.grouped_common_issue_ids(deterministic))
        ai_groups, valid = ui.validate_ai_common_issue_groups(
            {"groups": [{
                "heading": "内存训练问题",
                "common_problem_explanation": "两条 IPS 都描述了 DDR 内存训练失败。",
                "evidence_tier": "候选证据",
                "ips_ids": ["1", "2"],
                "grouping_reason": "问题正文都包含 DDR memory training error。",
            }]},
            issues,
            return_status=True,
        )
        self.assertTrue(valid)
        self.assertEqual({"1", "2"}, ui.grouped_common_issue_ids(ai_groups))

    def test_ai_evidence_tier_is_downgraded_without_verified_sighting(self) -> None:
        groups, valid = ui.validate_ai_common_issue_groups(
            {"groups": [{
                "heading": "Shared symptom",
                "common_problem_explanation": "Both records report the same timeout.",
                "evidence_tier": "强证据",
                "ips_ids": ["1", "2"],
                "grouping_reason": "Same customer-reported timeout.",
            }]},
            [{"ips_id": "1", "description": "Timeout"}, {"ips_id": "2", "description": "Timeout"}],
            return_status=True,
        )
        self.assertTrue(valid)
        self.assertEqual("候选证据", groups[0]["evidence_tier"])

    def test_common_issue_fallback_requires_shared_customer_description(self) -> None:
        groups = ui.build_common_issue_groups([
            {"ips_id": "1", "title": "Platform failure", "customer_description": "Cold boot DIMM training timeout at POST 31"},
            {"ips_id": "2", "title": "Unrelated title", "customer_description": "DIMM training timeout occurs during cold boot"},
            {"ips_id": "3", "title": "Platform failure", "customer_description": "Customer requests a BIOS feature explanation"},
        ])
        self.assertEqual(1, len(groups))
        self.assertEqual({"1", "2"}, ui.grouped_common_issue_ids(groups))
        self.assertIn("客户问题描述", groups[0]["records"][0]["grouping_reason"])

    def test_auto_query_assesses_each_ips_reference_value_without_grouping(self) -> None:
        analysis = ui.build_auto_query_common_issue_analysis(
            [
                {
                    "id": "10", "title": "Memory training timeout", "status": "open",
                    "server_platf_ae": {"bug": {
                        "int_sighting_url": "https://hsdes.intel.com/appstore/article_legacy/#/99",
                        "close_reason": "internal_fixed",
                        "fix_description": "Update BKC to resolve the timeout.",
                    }},
                    "description": "Cold boot DIMM training times out at POST 0x31.",
                    "failure_signature": "POST 0x31",
                },
                {
                    "id": "11", "title": "Different issue", "status": "closed", "description": "No actionable details.",
                    "bug.closed_reason": "internal_inquiry",
                },
            ],
            {"commonIssueAnalysis": {"aiEnrichmentEnabled": False}},
        )
        recommended = next(item for item in analysis["recommendations"] if item["ips_id"] == "10")
        self.assertEqual(2, analysis["total_ips"])
        self.assertEqual(1, analysis["open_ips"])
        self.assertEqual("强烈推荐", recommended["recommendation_level"])
        self.assertEqual(2, analysis["recommended_count"])
        self.assertEqual(2, len(analysis["candidate_assessments"]))
        rendered = ui.render_auto_common_issue_analysis(analysis)
        self.assertIn("Top 20 IPS", rendered)
        self.assertIn("Different issue", rendered)
        self.assertIn("Detailed IPS Matrix", rendered)
        self.assertIn("All analyzed IPS records", rendered)
        self.assertNotIn("Score breakdown", rendered)

    def test_auto_query_top_ips_sorts_by_reference_score_not_status(self) -> None:
        today = ui.date.today()
        rows = [
            {"id": "open", "status": "open"},
            {"id": "closed-common", "status": "closed"},
            {"id": "recent-closed", "status": "closed"},
            {"id": "older-closed", "status": "closed"},
        ]
        assessments = [
            {
                "ips_id": "open", "reference_score": 1, "recommendation_level": "推荐参考",
                "record": {"query_status": "open", "submitted_date": "2020-01-01"},
            },
            {
                "ips_id": "closed-common", "reference_score": 100, "recommendation_level": "推荐参考",
                "record": {"query_status": "closed", "closed_date": "2020-01-01"},
            },
            {
                "ips_id": "recent-closed", "reference_score": 99, "recommendation_level": "暂不推荐",
                "record": {"query_status": "closed", "closed_date": today.isoformat()},
            },
            {
                "ips_id": "older-closed", "reference_score": 98, "recommendation_level": "暂不推荐",
                "record": {"query_status": "closed", "closed_date": today.fromordinal(today.toordinal() - 15).isoformat()},
            },
        ]
        cfg = {
            "commonIssueAnalysis": {"referenceTopCount": 4},
        }
        with mock.patch.object(
            ui, "enrich_reference_assessments",
            return_value=(assessments, "ai_enriched", {"status": "validated", "limitation": ""}),
        ):
            analysis = ui.build_auto_query_common_issue_analysis(rows, cfg)
        self.assertEqual(
            ["closed-common", "recent-closed", "older-closed", "open"],
            [item["ips_id"] for item in analysis["recommendations"]],
        )

    def test_top_ips_matrix_includes_all_analyzed_statuses(self) -> None:
        today = ui.date.today()
        analysis = {
            "reference_top_count": 20,
            "recommendations": [],
            "candidate_assessments": [
                {
                    "ips_id": "open-old", "reference_score": 50, "summary": "Open issue",
                    "record": {
                        "query_status": "open", "submitted_date": "2020-01-01",
                        "component": "Memory", "owner": "Alice", "customer": "Example Customer",
                        "title": "Open memory issue",
                    },
                },
                {
                    "ips_id": "completed-recent", "reference_score": 40, "summary": "Recent issue",
                    "record": {
                        "query_status": "completed", "submitted_date": "2026-01-01",
                        "closed_date": today.fromordinal(today.toordinal() - 15).isoformat(),
                        "component": "Firmware", "title": "Recent firmware issue",
                    },
                },
                {
                    "ips_id": "complete-recent", "reference_score": 45, "summary": "Recent complete issue",
                    "record": {
                        "query_status": "complete", "submitted_date": "2026-01-01",
                        "closed_date": today.fromordinal(today.toordinal() - 12).isoformat(),
                        "component": "Firmware", "title": "Recent completed firmware issue",
                    },
                },
                {
                    "ips_id": "completed-old", "reference_score": 90, "summary": "Old issue",
                    "record": {
                        "query_status": "closed", "closed_date": "2020-01-01",
                        "component": "Memory", "title": "Old completed issue",
                    },
                },
            ],
        }
        rendered = ui.render_auto_common_issue_analysis(analysis)
        self.assertIn('data-domain="Memory"', rendered)
        self.assertIn('data-domain="Firmware"', rendered)
        self.assertIn("open-old", rendered)
        self.assertIn("completed-recent", rendered)
        self.assertIn("complete-recent", rendered)
        self.assertIn("completed-old", rendered)
        self.assertRegex(rendered, r">\d+d</td>")
        self.assertIn("<th>End</th>", rendered)
        self.assertIn("<th>Owner</th>", rendered)
        self.assertIn("<th>Customer company</th>", rendered)
        self.assertIn("<th>Cluster</th>", rendered)
        self.assertIn("<th>Reusable finding</th>", rendered)
        self.assertIn("<th>Smallest next check</th>", rendered)
        self.assertIn("<th>Internal link</th>", rendered)
        self.assertIn(today.fromordinal(today.toordinal() - 15).isoformat(), rendered)
        self.assertIn('id="dateFilter"', rendered)
        self.assertIn("Last 2 months", rendered)
        self.assertIn("Example Customer", rendered)
        self.assertIn("Alice", rendered)
        self.assertIn("Ranking rules", rendered)

    def test_completed_strong_evidence_outranks_open_content(self) -> None:
        today = ui.date.today()
        assessments = [
            {
                "ips_id": "open-content", "reference_score": 35, "content_score": 35,
                "recommendation_level": "暂不推荐",
                "record": {"query_status": "open", "submitted_date": today.isoformat()},
            },
            {
                "ips_id": "completed-strong", "reference_score": 100, "content_score": 60,
                "recommendation_level": "强烈推荐",
                "record": {"query_status": "completed", "closed_date": today.isoformat()},
            },
            {
                "ips_id": "open-low-value", "reference_score": 60, "content_score": 20,
                "recommendation_level": "暂不推荐",
                "record": {"query_status": "open", "submitted_date": today.isoformat()},
            },
            {
                "ips_id": "recent-completed", "reference_score": 20, "content_score": 20,
                "recommendation_level": "暂不推荐",
                "record": {"query_status": "completed", "closed_date": today.isoformat()},
            },
        ]
        ordered = sorted(
            assessments,
            key=ui.reference_assessment_sort_key,
        )
        self.assertEqual(
            ["completed-strong", "open-low-value", "open-content", "recent-completed"],
            [item["ips_id"] for item in ordered],
        )

    def test_auto_query_article_fetch_enriches_unique_rows_and_reports_failures(self) -> None:
        cfg = {
            "commonIssueAnalysis": {
                "autoQueryArticleFetchMaxCount": 100,
                "autoQueryArticleFetchConcurrency": 2,
                "autoQueryArticleFetchTimeoutSeconds": 7,
            }
        }

        def fetch(ips_id: str, timeout: int) -> dict:
            self.assertEqual(7, timeout)
            if ips_id == "11":
                raise RuntimeError("mock HSD failure")
            return {
                "id": ips_id,
                "title": "Fetched memory training symptom",
                "description": "Cold boot DIMM training reaches a timeout signature.",
                "status": "closed",
                "failure_signature": "POST 0x31",
            }

        rows = [
            {"id": "10", "status": "open", "title": "saved title"},
            {"id": "10", "status": "open", "title": "duplicate"},
            {"id": "11", "status": "resolved", "title": "saved failed article"},
        ]
        with mock.patch.object(ui, "fetch_hsd_article_content", side_effect=fetch) as patched:
            enriched, summary = ui.enrich_auto_query_article_rows(rows, cfg)
        self.assertEqual(["10", "11"], sorted(call.args[0] for call in patched.call_args_list))
        self.assertEqual(2, summary["requested"])
        self.assertEqual(1, summary["fetched"])
        self.assertEqual(1, summary["failed"])
        self.assertEqual(["11"], summary["failed_ids"])
        by_id = {row["id"]: row for row in enriched}
        self.assertEqual("open", by_id["10"]["query_status"])
        self.assertEqual("open", by_id["10"]["status"])
        self.assertEqual("Cold boot DIMM training reaches a timeout signature.", by_id["10"]["description"])
        self.assertFalse(by_id["11"]["article_content_fetched"])

    def test_auto_query_article_selection_keeps_all_open_and_newest_terminal_ips(self) -> None:
        rows = {
            "open-old": {"status": "open", "submitted_date": "2026-08-01"},
            "open-new": {"status": "open", "submitted_date": "2026-09-01"},
            "complete-old": {"status": "complete", "closed_date": "2026-08-01"},
            "complete-new": {"status": "complete", "closed_date": "2026-09-01"},
            "complete-mid": {"status": "complete", "closed_date": "2026-08-20"},
        }
        self.assertEqual(
            ["open-new", "open-old", "complete-new", "complete-mid"],
            ui.select_auto_query_article_ids(rows, 4),
        )
        open_only = {
            **{f"open-{index}": {"status": "open", "submitted_date": f"2026-08-{index:02d}"} for index in range(1, 6)},
            "complete-new": {"status": "complete", "closed_date": "2026-09-01"},
        }
        self.assertEqual(
            ["open-5", "open-4", "open-3"],
            ui.select_auto_query_article_ids(open_only, 3),
        )

    def test_execute_hsd_query_reads_every_page_for_reference_reports(self) -> None:
        first = mock.Mock(
            returncode=0, stderr="", stdout=json.dumps({"total": 3, "data": [{"id": "1"}, {"id": "2"}]})
        )
        second = mock.Mock(
            returncode=0, stderr="", stdout=json.dumps({"total": 3, "data": [{"id": "3"}]})
        )
        with mock.patch.object(ui.subprocess, "run", side_effect=[first, second]) as run:
            rows = ui.execute_hsd_query("15019757863", all_pages=True)
        self.assertEqual(["1", "2", "3"], [row["id"] for row in rows])
        self.assertTrue(run.call_args_list[0].args[0][-1].endswith("?start_at=1"))
        self.assertTrue(run.call_args_list[1].args[0][-1].endswith("?start_at=3"))

    def test_auto_query_fetches_int_sighting_context_once_and_adds_it_to_analysis(self) -> None:
        rows = [{
            "id": "10",
            "status": "open",
            "server_platf_ae.bug.int_sighting_url": "https://hsdes.intel.com/appstore/article/#/14000000099",
        }]

        def fetch(ips_id: str, timeout: int) -> dict:
            if ips_id == "10":
                return {"id": "10", "description": "Customer reports a cold boot timeout."}
            self.assertEqual("14000000099", ips_id)
            return {
                "id": "14000000099",
                "description": "Known memory-training failure.",
                "root_cause": "Firmware timing issue.",
                "bug": {"fix_description": "Update BKC 2.0."},
            }

        with mock.patch.object(ui, "fetch_hsd_article_content", side_effect=fetch) as patched:
            enriched, summary = ui.enrich_auto_query_article_rows(rows, {})
        self.assertEqual(["10", "14000000099"], sorted(call.args[0] for call in patched.call_args_list))
        self.assertEqual(1, summary["sighting_requested"])
        self.assertEqual(1, summary["sighting_fetched"])
        self.assertIn("Firmware timing issue.", enriched[0]["int_sighting_context"])
        normalized = ui.normalize_common_issue_row(enriched[0])
        self.assertIn("Internal sighting context:", normalized["analysis_text"])
        self.assertIn("Update BKC 2.0.", normalized["analysis_text"])

    def test_auto_query_article_fetch_helper_uses_authenticated_article_endpoint(self) -> None:
        result = mock.Mock(
            returncode=0, stderr="", stdout=json.dumps({"data": [{"id": "10", "description": "full article body"}]})
        )
        with mock.patch.object(ui.subprocess, "run", return_value=result) as run:
            article = ui.fetch_hsd_article_content("10", 45)
        self.assertEqual("full article body", article["description"])
        command = run.call_args.args[0]
        self.assertEqual(["curl.exe", "--noproxy", "*", "--negotiate", "-u", ":"], command[:6])
        self.assertEqual("https://hsdes-api.intel.com/rest/article/10", command[-1])
        self.assertEqual(45, run.call_args.kwargs["timeout"])

    def test_auto_query_assessment_sends_article_content_to_ai_and_renders_fetch_scope(self) -> None:
        rows = [
            {
                "id": "10", "query_status": "open", "article_content_fetched": True,
                "title": "Memory training timeout", "description": "Cold boot DIMM training times out at POST 0x31.",
                "failure_signature": "POST 0x31",
                "server_platf_ae.bug.int_sighting_url": "https://hsdes.intel.com/appstore/article/#/99",
            },
            {
                "id": "11", "query_status": "closed", "article_content_fetched": True,
                "title": "Memory training timeout", "description": "Cold boot DIMM training times out at POST 0x31.",
                "bug.closed_reason": "internal_fixed",
            },
        ]
        response = {"recommendations": [
            {
                "ips_id": "10", "problem_score": 25, "reuse_score": 27, "applicability_score": 5, "recommendation_level": "推荐参考",
                "summary": "Memory training timeout", "reuse_reason": "No internal reference field.",
                "applicability": "BHS cold boot", "limitations": "Missing internal signals.",
            },
            {
                "ips_id": "11", "problem_score": 20, "reuse_score": 21, "applicability_score": 5, "recommendation_level": "推荐参考",
                "summary": "Memory training timeout", "reuse_reason": "No internal reference field.",
                "applicability": "BHS cold boot", "limitations": "Missing internal signals.",
            },
        ]}
        cfg = {
            "commonIssueAnalysis": {"aiEnrichmentEnabled": True},
            "copilot": {"mode": "subprocess", "stage2Mode": "subprocess"},
        }
        fetch_summary = {
            "unique_numeric_ips": 3, "requested": 2, "fetched": 2, "failed": 0,
            "skipped_by_limit": 1, "max_count": 2, "failed_ids": [],
            "limitation": "Blocking limitation: analyzed subset.",
        }
        with mock.patch.object(ui, "run_copilot", return_value=(0, json.dumps(response))) as run:
            analysis = ui.build_auto_query_common_issue_analysis(rows, cfg, fetch_summary)
        prompt = run.call_args.args[0]
        self.assertIn("Cold boot DIMM training times out at POST 0x31.", prompt)
        self.assertIn("Failure signature: POST 0x31", prompt)
        self.assertIn("Evaluate every supplied IPS candidate independently", prompt)
        self.assertEqual("ai_enriched", analysis["analysis_mode"])
        self.assertEqual("analyzed_query_subset", analysis["source"])
        rendered = ui.render_auto_common_issue_analysis(analysis)
        self.assertIn("Top 20 IPS", rendered)
        self.assertIn("Detailed IPS Matrix", rendered)
        self.assertIn("Scoring and eligibility rules are unchanged.", rendered)
        self.assertNotIn("Score breakdown", rendered)
        self.assertNotIn("Blocking limitation: analyzed subset.", rendered)

    def test_common_issue_search_uses_documented_eql_request(self) -> None:
        cfg = {"commonIssueAnalysis": {"requestTimeoutSeconds": 17}}
        filters = ui.validate_common_issue_filters(
            {
                "platform": "BHS",
                "customer": "",
                "submitted_start_date": "2026-01-01",
                "submitted_end_date": "2026-01-02",
                "component": "",
                "keywords": "",
                "result_limit": 10,
            },
            cfg,
        )
        result = mock.Mock(returncode=0, stderr="", stdout='{"data":[{"id":"1"}]}')
        with mock.patch.object(ui.subprocess, "run", return_value=result) as run:
            self.assertEqual([{"id": "1"}], ui.execute_common_issue_search(filters, cfg))
        command = run.call_args.args[0]
        request = json.loads(command[command.index("--data") + 1])
        self.assertEqual({"eql"}, set(request))
        self.assertNotIn("parameters", request)
        self.assertIn("submitted_date >= '2026-01-01 00:00:00'", request["eql"])
        self.assertIn("submitted_date <= '2026-01-02 23:59:59'", request["eql"])
        self.assertIn("family = 'Birch Stream Platform'", request["eql"])
        self.assertEqual("https://hsdes-api.intel.com/rest/query/execution/eql?start_at=1", command[-1])
        self.assertEqual(17, run.call_args.kwargs["timeout"])

    def test_common_issue_eql_allows_multiple_customers(self) -> None:
        cfg = {}
        filters = ui.validate_common_issue_filters(
            {
                "platform": "OKS",
                "customer": "MagInfra/Lenovo；H3C,Alibaba",
                "submitted_start_date": "2026-02-01",
                "submitted_end_date": "2026-05-01",
            },
            cfg,
        )
        eql, _ = ui.build_common_issue_eql(filters, ui.common_issue_config(cfg))
        customer_field = "server_platf_ae.bug.ext_account_name"
        self.assertIn(
            f"({customer_field} = 'Maginfra Co., Ltd.' OR {customer_field} = 'Lenovo' OR "
            f"{customer_field} = 'New H3C Information Technologies Co., Ltd' OR {customer_field} = 'Alibaba')",
            eql,
        )
        self.assertIn("family = 'Oak Stream DMR Platforms'", eql)

    def test_common_issue_ai_enrichment_uses_read_only_prompt_and_validator(self) -> None:
        previous_store = ui.COMMON_ISSUE_STORE
        previous_search = ui.execute_common_issue_search
        report_dir = self.work / "common_issue_ai_reports"
        cfg = {
            "commonIssueAnalysis": {"reportDirectory": str(report_dir), "aiTimeoutSeconds": 12},
            "copilot": {"mode": "subprocess", "stage2Mode": "subprocess"},
        }
        ui.COMMON_ISSUE_STORE = None
        ui.execute_common_issue_search = lambda _filters, _cfg: [
            {"id": "1", "title": "Memory training failure", "description": "DIMM training fails after a cold boot.", "platform": "BHS", "component": "Memory", "submitted_date": "2026-01-02"},
            {"id": "2", "title": "Memory initialization failure", "description": "DIMM training fails after a cold boot.", "platform": "BHS", "component": "Memory", "submitted_date": "2026-01-02"},
        ]
        filters = ui.validate_common_issue_filters(
            {"platform": "BHS", "submitted_start_date": "2026-01-01", "submitted_end_date": "2026-01-02"},
            cfg,
        )
        response = {
            "groups": [{
                "heading": "Memory training common problem",
                "common_problem_explanation": "The normalized records have the same memory-training symptom.",
                "evidence_tier": "候选证据",
                "ips_ids": ["1", "2"],
                "grouping_reason": "Matching normalized title and component.",
            }]
        }
        try:
            with mock.patch.object(ui, "run_copilot", return_value=(0, json.dumps(response))) as run:
                report = ui.create_common_issue_report(filters, cfg)
            prompt = run.call_args.args[0]
            self.assertIn("Do not use tools, skills, terminals, files, network access, SSH, or any hardware action.", prompt)
            self.assertIn("strict schema exactly", prompt)
            self.assertIn("DIMM training fails after a cold boot.", prompt)
            self.assertEqual("ai_enriched", report["analysis_mode"])
            self.assertEqual("validated", report["ai_enrichment"]["status"])
            self.assertIn("same memory-training symptom", report["groups"][0]["common_problem_explanation"])
        finally:
            ui.execute_common_issue_search = previous_search
            ui.COMMON_ISSUE_STORE = previous_store

    def test_common_issue_ai_falls_back_for_manual_or_invalid_output(self) -> None:
        issues = [{"ips_id": "1", "title": "Memory failure", "platform": "BHS", "component": "Memory"}]
        manual_cfg = {"commonIssueAnalysis": {}, "copilot": {"mode": "manual"}}
        groups, mode, enrichment = ui.enrich_common_issue_groups(
            issues, manual_cfg, ui.common_issue_config(manual_cfg)
        )
        self.assertEqual("deterministic_fallback", mode)
        self.assertEqual("manual_or_handoff", enrichment["status"])
        self.assertEqual(ui.build_common_issue_groups(issues), groups)

        invalid_cfg = {"commonIssueAnalysis": {}, "copilot": {"mode": "subprocess", "stage2Mode": "subprocess"}}
        with mock.patch.object(ui, "run_copilot", return_value=(0, "not JSON")):
            _, mode, enrichment = ui.enrich_common_issue_groups(
                issues, invalid_cfg, ui.common_issue_config(invalid_cfg)
            )
        self.assertEqual("deterministic_fallback", mode)
        self.assertEqual("invalid_response", enrichment["status"])

    def test_common_issue_search_api_persists_without_real_hsd(self) -> None:
        previous_store = ui.COMMON_ISSUE_STORE
        previous_search = ui.execute_common_issue_search
        report_dir = self.work / "common_issue_reports"
        cfg = {"commonIssueAnalysis": {"reportDirectory": str(report_dir), "maxDateRangeDays": 30, "defaultResultLimit": 10, "maxResultLimit": 20}}
        ui.COMMON_ISSUE_STORE = None
        ui.execute_common_issue_search = lambda _filters, _cfg: [
            {
                "id": "14025984558",
                "title": "Memory initialization fails",
                "platform": "BHS",
                "customer": "Example",
                "component": "Memory",
                "submitted_date": "2026-01-02",
                "in_sighting": "14025000000",
            },
            {
                "id": "14025984559",
                "title": "Memory initialization fails again",
                "platform": "BHS",
                "customer": "Example",
                "component": "Memory",
                "submitted_date": "2026-01-02",
                "in_sighting": "14025000000",
            },
        ]
        try:
            handler = object.__new__(ui.Handler)
            response = {}
            handler.cfg = cfg
            handler.path = "/api/common-issues/search"
            handler._read_json = lambda: {
                "platform": "BHS",
                "customer": "",
                "submitted_start_date": "2026-01-01",
                "submitted_end_date": "2026-01-02",
                "component": "",
                "keywords": "",
                "result_limit": 10,
            }
            handler._send_json = lambda data, status=200: response.update(data=data, status=status)
            handler.do_POST()
            self.assertEqual(200, response["status"])
            report_id = response["data"]["id"]
            self.assertTrue((report_dir / report_id / "report.json").exists())
            self.assertEqual("强证据", response["data"]["groups"][0]["evidence_tier"])

            handler.path = "/api/common-issues/reports"
            handler.do_GET()
            self.assertEqual(report_id, response["data"]["reports"][0]["id"])
            handler.path = f"/api/common-issues/reports/{report_id}"
            handler.do_GET()
            self.assertEqual(report_id, response["data"]["report"]["id"])
        finally:
            ui.execute_common_issue_search = previous_search
            ui.COMMON_ISSUE_STORE = previous_store

    def test_common_issue_feedback_is_persisted_and_attached_to_report(self) -> None:
        store = ui.CommonIssueReportStore(self.work / "common_issue_feedback")
        filters = ui.CommonIssueFilters("BHS", "", "2026-01-01", "2026-01-02", "", "", 10)
        record = store.create(filters)
        report = {
            "id": record["id"],
            "groups": [{
                "grouping_key": "sighting|14025000000",
                "heading": "Shared sighting",
                "records": [{"ips_id": "1"}, {"ips_id": "2"}],
            }],
        }
        store.update(record["id"], "completed", report)
        updated = store.add_feedback(record["id"], "sighting|14025000000", "confirmed", "Verified same workaround.")
        self.assertEqual("confirmed", updated["report"]["feedback"][0]["action"])
        self.assertIn("Verified same workaround.", ui.common_issue_feedback_label(updated["report"], "sighting|14025000000"))
        with self.assertRaises(ValueError):
            store.add_feedback(record["id"], "sighting|14025000000", "invalid", "")

    def test_common_issue_report_hides_raw_grouping_evidence(self) -> None:
        rendered = ui.render_common_issue_report_content(
            {
                "groups": [{
                    "heading": "Memory training",
                    "evidence_tier": "候选证据",
                    "confidence_score": 70,
                    "evidence_signals": ["共同问题关键词：bella, br, hi"],
                    "common_problem_explanation": "Customer reports the same training timeout.",
                    "grouping_key": "ai|1|2",
                    "records": [{"ips_id": "1"}, {"ips_id": "2"}],
                }],
            }
        )
        self.assertNotIn("归并依据", rendered)
        self.assertNotIn("bella, br, hi", rendered)


if __name__ == "__main__":
    unittest.main()
