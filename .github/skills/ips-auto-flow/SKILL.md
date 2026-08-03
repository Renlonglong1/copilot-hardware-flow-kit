---
name: ips-auto-flow
description: "Use when: the IPS/HSD Copilot UI full-automatic mode processes an Open IPS selected from an HSD saved query. It extracts the issue, safely matches a lab machine and BKC, runs required validation, analyzes logs, writes a report, and automatically emails the IPS owner."
---

# IPS / HSD Full-Automatic Flow

Use this skill only for one IPS explicitly supplied by the full-automatic UI. Do not query for or process any other IPS.

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
3. Extract the title, owner, platform, topology, BKC/software version, problem description, customer request, repro data, comments, attachments, root cause/fix/workaround, and relevant similar IPS experience.
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

The Markdown report is the detailed execution record. It must state the reasoning and machine/BKC matching decisions, environment comparison, hardware operations and commands, evidence paths, measured results, whether the issue was reproduced, not reproduced, partially reproduced, blocked, or skipped, and remaining gaps. For a non-identical but compatible lab environment, it must state the local measured result, material configuration/tool differences, and whether a quantitative comparison with the customer is valid.

The email body is a detailed staff-facing working conclusion. It must contain `客户机器环境`, `客户问题`, `诊断结果`, `问题排查`, `重点关注`, `下一步研究方向`, and `完整报告`. It must emphasize the test conclusion and key measured evidence, investigation findings and leading hypothesis, unresolved risks, and concrete next validation direction. It must explicitly state whether hardware actions ran, without duplicating the full command-by-command execution record in the Markdown attachment.

## Safety Rules

- Never request, store, or expose passwords, cookies, tokens, Kerberos ticket contents, or SSH private keys.
- Never process a non-Open IPS.
- Never flash unless the platform, machine, BKC, target image, size, and SHA256 are verified.
- Flash success requires `Download Complete`, `Verify Pass`, `Emulator is in Emulation mode`, and `Authentication Pass`.
- If EM100 reports `No device is connected!`, inspect DediProg USB and GUI ownership before retrying.
- A blocked or failed IPS still needs a report and owner notification; do not silently skip it.
