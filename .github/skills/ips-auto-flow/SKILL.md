---
name: ips-auto-flow
description: "Use when: the IPS/HSD Copilot UI full-automatic mode processes one Open IPS selected from an HSD saved query. It respects the upstream independent IPS reference-value assessment, then safely extracts the current issue, matches a lab machine and BKC, runs required validation, analyzes logs, writes a report, and emails the IPS owner. Use only for the one Open IPS explicitly supplied by the UI."
---

# IPS / HSD Full-Automatic Flow

Use this skill only for one Open IPS explicitly supplied by the full-automatic UI. Do not query for or process any other IPS. Query-wide IPS reference-value selection is performed upstream as a separate read-only flow; it evaluates each IPS independently and does not assert a shared root cause.

## Query IPS Reference-Value Boundary

The upstream Query analysis fetches and assesses every IPS body in batches. For each unique valid `server_platf_ae.bug.int_sighting_url`, it also read-only fetches the linked SI/FW article once and appends its description, comments, root cause, fix/workaround, and repro/debug information as internal-sighting context. `bug.closed_reason` / `close_reason` beginning with `internal_` and the normalized SI/FW link are scoring evidence, not admission gates. The UI normalizes XML/HTML-formatted sighting values into a clickable SI/FW link. AI scores the combined current-IPS and SI/FW context, then reports only the highest-ranked entries; records outside the configured Top count are not shown.

1. Treat the current IPS independently; do not infer a common issue, common root cause, or Debug skip from other Query records.
2. Verify the current IPS content: reported symptom, trigger/configuration, impact, failure signature, root cause, fix/workaround, and repro/debug details.
3. Only describe a case as reusable when its content supplies a recognizable problem pattern and useful handling, diagnosis, root cause, fix, workaround, or reproduction direction.
4. Use platform, release, component, project, and priority only to state applicability boundaries.
5. Do not treat a Top-ranked IPS as proof that multiple Query IPS share one root cause. It is an individually ranked cross-team reference.

The report displays a compact ranked card for each selected IPS: AI score, IPS title/link, Query status, explicit `int_sighting_url` SI/FW link when available, internal close-reason tag, problem summary, selection rationale, applicability, and limitations. Do not require or render unselected IPS. The ranked cards are shown only on the dedicated Query Top IPS reference report; the Query execution report links to it and remains focused on task execution.

## Reference-report-only mode

When the UI user selects **仅生成共性报告**, run exactly one read-only Query pass: fetch Query IPS articles and linked `int_sighting_url` articles, then rank the Top IPS reference report. Do not process Open IPS, invoke the auto-debug execution prompt, acquire hardware resources, poll, send manager notifications, SSH, flash, power cycle, capture serial, or run MLC.

## Required Reading

Before hardware work, read:

1. `docs\hsd_python_api_notes.md`
2. `docs\bhs_uplr2_robust_full_flow.md`
3. `docs\mlc_command_manual.md`
4. `docs\lab_machine_inventory.md`
5. `config\lab-machine-inventory.json`

Read `config\bkc-remote-inventory.dbgsh05.json` when selecting a BKC image.

## Workflow

1. Fetch the requested IPS/HSD article using `scripts\Invoke-HsdArticleFetch.ps1`.
2. Confirm the article status is still `open`. If it is not Open, write a short skipped report under `out\<articleId>\` and stop.
3. Extract the title, owner, platform, topology, BKC/software version, problem description, customer request, repro data, comments, attachments, root cause/fix/workaround, and relevant similar IPS experience. Apply the Query IPS Reference-Value Boundary before choosing hardware work.
4. Match a compatible control machine using the lab inventory. Platform mismatch, incomplete platform evidence, missing BKC, or unavailable capability is a blocking result; do not guess or substitute another platform.
5. Perform hardware validation only when it is relevant and the compatibility checks pass. Follow the validated hardware flow: precheck target/EM100/USB, verify BKC image and SHA256, and fail fast after any flash failure. Do not collect boot logs or run MLC after a failed flash.
6. Capture raw boot/test logs, analyze the saved artifacts, and distinguish actual defects from configuration, tool/version, topology, BIOS setting, or workload differences. When the compatible lab machine is not configuration-identical to the customer system, still run feasible issue-relevant tests; report the local measured result and differences, and do not treat it as quantitatively identical to the customer result.
7. Save all artifacts and a detailed Markdown execution report to `out\<articleId>\`. The report records the reasoning and decisions, customer/lab machine matching, configuration comparison, hardware actions, commands, evidence paths, measured results, and limitations.
8. Send the final result to the owner with a detailed, staff-facing working-conclusion email body and the Markdown report attached:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To '<owner>' -Subject '[Copilot][HSD] <articleId> debug completed - <status>' -Body '<summary>' -Attachments 'out\<articleId>\<report>.md' -IncludeMlcResults -Send
```

Include `-IncludeMlcResults` only when an MLC test ran. It attaches the latest complete `host_mlc_results.log` from the HSD output directory with the report.

## Report and Email Requirements

The Markdown report is the detailed execution record. It must state the reasoning and machine/BKC matching decisions, environment comparison, hardware operations and commands, evidence paths, measured results, whether the issue was reproduced, not reproduced, partially reproduced, blocked, or skipped, and remaining gaps. Include a `共性问题关联与历史复用判断` section whenever Query context was supplied. For a non-identical but compatible lab environment, it must state the local measured result, material configuration/tool differences, and whether a quantitative comparison with the customer is valid.

The email body is a detailed staff-facing working conclusion. It must contain `客户机器环境`, `客户问题`, `诊断结果`, `问题排查`, `重点关注`, `下一步研究方向`, and `完整报告`. It must emphasize the test conclusion and key measured evidence, investigation findings and leading hypothesis, unresolved risks, and concrete next validation direction. It must explicitly state whether hardware actions ran, without duplicating the full command-by-command execution record in the Markdown attachment.

## Safety Rules

- Never request, store, or expose passwords, cookies, tokens, Kerberos ticket contents, or SSH private keys.
- Never process a non-Open IPS.
- Never flash unless the platform, machine, BKC, target image, size, and SHA256 are verified.
- Flash success requires `Download Complete`, `Verify Pass`, `Emulator is in Emulation mode`, and `Authentication Pass`.
- If EM100 reports `No device is connected!`, inspect DediProg USB and GUI ownership before retrying.
- A blocked or failed IPS still needs a report and owner notification; do not silently skip it.
