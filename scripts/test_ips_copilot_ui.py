"""Focused stdlib tests for persistent Query task management."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import unittest


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
        self.assertTrue(store.try_acquire_machine(running["id"], "dbgsh05"))
        self.assertFalse(store.try_acquire_machine("other-task", "dbgsh05"))

        restarted = ui.TaskStore(self.database, {"default": 1})
        self.assertEqual("interrupted", restarted.get_task(running["id"])["status"])
        self.assertIn("restarted", restarted.get_task(running["id"])["cancellation_reason"])
        self.assertFalse(restarted.try_acquire_machine("other-task", "dbgsh05"))
        restarted.release_machine(running["id"], "dbgsh05")
        self.assertTrue(restarted.try_acquire_machine("other-task", "dbgsh05"))

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
        finally:
            ui.AUTO_REPORTS_DIR = previous

    def test_task_api_posts_without_external_services(self) -> None:
        class Manager:
            def __init__(self) -> None:
                self.started = None
                self.cancelled = None

            def start(self, query_id, creator_name, interval_minutes, manager_recipients):
                self.started = (query_id, creator_name, interval_minutes, manager_recipients)
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
            self.assertEqual(("300", "Carol", 60, "manager@example.test"), manager.started)
            task_id = "123e4567-e89b-12d3-a456-426614174000"
            self.assertEqual(task_id, response["data"]["id"])

            handler.path = f"/api/tasks/{task_id}/cancel"
            handler._read_json = lambda: {"reason": "user stopped it"}
            handler.do_POST()
            self.assertEqual((task_id, "user stopped it"), manager.cancelled)
            self.assertEqual("cancelled", response["data"]["status"])

            handler.path = "/api/tasks"
            handler.do_GET()
            self.assertEqual("queued", response["data"]["tasks"][0]["status"])
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


if __name__ == "__main__":
    unittest.main()
