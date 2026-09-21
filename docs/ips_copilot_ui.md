# UI operation guide

See chapters 2–10 of `SYSTEM_HANDOVER.zh-CN.md` for architecture, state transitions,
configuration, workflow boundaries, reports, recovery and maintenance.

The default URL is `http://127.0.0.1:8765/`.
Pages include `/`, `/tasks`, `/reports`, `/common-issues` and `/guide`.
The task center is a read-only progress view; use the workbench's task controls
to submit or cancel work.

The template uses subprocess execution for Stage 1 and Stage 2. Stage 1 only
plans; extraction/consultation never operates hardware. `handoff` writes a task
file for a suitably authorized interactive session and is not proof of execution.

Automatic Query requires both modes to be subprocess. The task database is
`out\ui_task_manager.sqlite3`; interrupted active tasks are not automatically
resumed after restart. Cancelling cannot undo completed hardware actions.

Manual records and summary files live under `out\manual_reports`.
Query rounds live under
`out\auto_reports\query_<ID>\task_<TaskId>\round_<N>\round.json`.
Common-issue reports live under `out\common_issue_reports\<uuid>\report.json`.
Missing current-task artifacts are not replaced with stale reports.

The service has no built-in authentication. Keep loopback binding unless an
approved access-controlled deployment is in place. Sender fields are audit
labels, not authenticated user identities. Back up state consistently and do not
share databases or raw reports through GitHub.
