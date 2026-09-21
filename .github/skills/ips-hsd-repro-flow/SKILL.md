---
name: ips-hsd-repro-flow
description: "Use when: the user asks Copilot to analyze an IPS/HSD issue by ID, extract owner/BKC/problem summary, map the requested BKC to a remote .bin image, flash the image on a lab server, run boot/MLC validation, and produce a Markdown reproduction report."
---

# IPS / HSD Hardware Reproduction Flow Skill

Use this skill for end-to-end IPS/HSD issue analysis plus hardware validation.

## Required Reading

Before acting, read:

1. `docs\hsd_python_api_notes.md`
2. `docs\bhs_uplr2_robust_full_flow.md`
3. `docs\mlc_command_manual.md`
4. `config\local\hardware-flow.json`
5. `config\local\bkc-inventory.json` if the request involves BKC image selection
6. `docs\lab_machine_inventory.md` for the approved inventory contract

## Inputs to Extract From the User Request

Identify and normalize:

- IPS/HSD article ID
- requested platform or family, such as BHS, GNR-SP, OKS, GNR CPU
- requested BKC, for example `2025_WW03`, `WW03`, `35.D23`, `30.D61`
- test target, such as MLC, cross-NUMA bandwidth, boot-only, serial log capture
- whether to search similar IPS/HSD issues for reusable experience
- whether to download and analyze customer attachments
- whether to notify owner/test recipient after completion
- requested output location, if provided
- server preference, if provided

If the request lacks a server, consult the approved local inventory and hardware
profile. Missing or incompatible platform evidence is blocking; do not select
a historical or documentation-only target. Verify host identity and approved
host-key aliases before connecting. Never bypass host-key verification.

## Lab and Customer Environment Differences

An exact customer-equivalent lab configuration is preferred, but BIOS settings, DIMM population/topology, CPU stepping/QDF, OS settings, and tool versions can differ even on a compatible platform.

- Do not substitute an incompatible platform or unverified BKC; those remain blocking.
- When the platform is compatible but configuration or tool differences remain, run the feasible issue-relevant test rather than skipping it solely for that reason.
- Record the local measured result, the known environment differences, and whether they prevent a quantitative comparison with the customer result.
- Never claim that a local value is identical to the customer value without matching evidence. Use `partially reproduced` when the behavior is observed but an exact comparison is not justified.

## HSD Extraction Contract

Use the helper first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <articleId>
```

If Python Kerberos returns a generic 403 HTML response, use the direct curl fallback already built into the helper or run with `-ForceCurlDirect`.

Extract at minimum:

- title
- tenant / subject
- status
- family / release / component
- owner, co-owner, support owner, owner org
- priority
- suspected problem area
- BKC or software version fields
- problem description
- customer reproduction steps
- comments / external customer blog history
- fix description / root cause / workaround, if present

Do not ask for or store passwords, cookies, SSO tokens, service tokens, or Kerberos ticket contents.

## Similar IPS Search, If Requested

If the final plan asks to search similar IPS/HSD issues:

1. Read the target IPS/HSD first.
2. Build focused search terms from title, family, release, component, suspected problem area, tag, BKC/software version, and important keywords.
3. Search HSD/HSDES for similar issues before hardware execution.
4. Extract reusable experience such as root cause, workaround, fix, comments, BIOS knobs, known limitations, and repro methods.
5. Include relevant similar issue IDs and why they matter in the final report.
6. Do not let noisy search results override direct evidence from the target issue or hardware validation.

## Customer Attachment Download, If Requested

If the final plan asks to download/analyze customer attachments:

1. Inspect HSD attachment fields such as:
   - `server_platf_ae.bug.download_attached_ips_files`
   - `server_platf_ae.bug.ext_attach_url`
   - other fields containing `attach`, `file`, or `overview`.
2. Download using the existing Windows/Kerberos context where possible. Do not ask for or store secrets.
3. Save under:

```text
out\<articleId>\attachments\
```

4. Extract archives when possible.
5. Prioritize Overview/README/summary/config/log/result/MLC/BIOS files.
6. Use attachment findings to refine BKC matching, repro steps, expected results, and report conclusions.
7. If download fails, document the link/field and failure reason in the final report.

## Completion Notification, If Requested

If the final plan asks to notify after completion:

1. Generate both final deliverables first:
   - Email body: a detailed, standalone working conclusion for the responsible staff, focused on test outcome, investigation findings, unresolved risks, and next steps.
   - Markdown report: the detailed execution record, including reasoning and decisions, machine/platform/BKC matching, configuration comparison, commands and hardware actions, artifact paths, measured results, and limitations.
2. Default recipient is the HSD/IPS owner extracted from the article owner field.
3. If the final plan explicitly says to use an override/test recipient, use that recipient instead. During testing, the common override recipient is:

```text
Li, Renlong
```

4. Use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Send-OwnerNotification.ps1 -To '<owner-or-override-recipient>' -Subject '<subject>' -Body '<body>' -Attachments '<report-path>'
```

When MLC was run, add `-IncludeMlcResults`. It locates the latest complete `host_mlc_results.log` beneath the report's HSD output directory and attaches it with the report. Do not use this switch when no MLC test was run.

By default this displays an Outlook draft. Add `-Send` only when the final plan explicitly says automatic email sending is enabled.

5. The body must be a detailed, standalone working conclusion rather than a report-path notice. Include the customer environment, customer problem, test conclusion and key measured evidence, investigation findings and leading hypothesis, unresolved risks or gaps, and concrete next research direction. Keep the full execution chronology, matching rationale, commands, and complete artifact inventory in the attached Markdown report.

Subject format:

```text
[Copilot][HSD] <articleId> <task-type> completed - <short status>
```

Body format:

```text
HSD/IPS ID: <id>
标题: <title>
Owner: <owner>
任务类型: <debug>

客户机器环境
- <platform/model, socket/NUMA or DIMM topology, BKC/BIOS, OS, tool/version, key configuration; use “未获取” where no evidence exists>

客户问题
- <symptom, impact, and customer request>

诊断结果
- <reproduction/validation state, final conclusion, key measured evidence, and hardware actions performed>

问题排查
- <key checks performed, findings, leading root-cause hypothesis, and ruled-out causes where applicable>

重点关注
- <unresolved risks, limitations, unverified assumptions, customer/lab environment differences, or decisions requiring follow-up>

下一步研究方向
- <concrete validation, configuration comparison, data collection, or owner follow-up, with expected decision value; state why if no action is needed>

完整报告
- Markdown 报告已作为附件：<report path>
```

## BKC Image Matching Contract

Map the HSD BKC to a remote `.bin` image.

Preferred mapping sources:

1. Explicit HSD BKC/software version fields.
2. HSD description text, for example `BHS 2S 2025_WW03`.
3. Local inventory files in `config\`.
4. Direct remote enumeration under `C:\Users\debug\Desktop\BKC`.

Selection rules:

- Prefer a BKC folder matching the HSD version, for example `GNRSP_25WW03`.
- Prefer full IFWI images unless the validated flow for that platform uses 64 MB images.
- For BHS uPLR/lab-control-05, 64 MB IFWI images can be valid and were used successfully in prior validation.
- `_2s` means 2S/2P.
- `1P0` / `IBL1P0` means 1S/1P.
- Small `capsule`, `mmc`, `swap`, `base_*`, `GoldScripts`, and `setup_ubios` binaries are support/component files, not default full-system flash images.
- Record selected bin path, size, SHA256, and why it was selected.

## Hardware Execution Contract

Before flashing:

1. Confirm the remote hostname/IP and BKC folder.
2. Confirm the bin exists and compute SHA256.
3. Check DediProg/EM100 process state.
4. Check USB device status.
5. Run `smucmd -c`.

If `No device is connected!` appears while USB shows DediProg is present, check and close `EM100.exe` / `Emulator.exe` GUI conflicts by PID, then recheck.

Programming rules:

- Power off before programming.
- Flash success requires all of:
  - `Download Complete`
  - `Verify Pass`
  - `Emulator is in Emulation mode`
  - `Authentication Pass`
- If flashing fails, stop and diagnose. Do not start long serial capture after a failed flash.

Boot validation:

- Open COM3/COM4 capture first.
- Power on after serial capture is ready or assumed ready.
- Capture full raw logs.
- Confirm COM3 boot signals such as `CentOS Stream 9`, `gnr-bkc login`, `ScktId`, or `Training`.
- Confirm COM4 BMC signals such as `U-Boot`, `Linux`, `OpenBMC`, or `login:`.

MLC validation:

- Use `/root/mlc_v3.11b` unless HSD or user specifies otherwise.
- Run the issue-relevant MLC command first, then broader baseline commands when useful.
- Save each MLC command output as a separate log file.
- Verify saved result logs contain `EXIT:0`; do not trust wrapper summary alone if serial log evidence says otherwise.

Default MLC commands for memory/NUMA issues:

```bash
./mlc --idle_latency
./mlc --latency_matrix
./mlc --bandwidth_matrix
./mlc --peak_injection_bandwidth
./mlc --loaded_latency
./mlc --c2c_latency
```

## Report Contract

Save the report and all task artifacts under the IPS/HSD-specific directory unless the user requests another location:

```text
out\<articleId>\hsd_<articleId>_<short-topic>_repro_report.md
```

The report must include:

1. HSD/IPS key information.
2. Extracted customer problem summary and requested outcome.
3. Reasoning and decisions: chosen lab machine, platform/topology/BKC/image matching rationale, and rejected alternatives if relevant.
4. Lab machine configuration and comparison with available customer environment evidence.
5. Hardware operation record: prechecks, flash, power, serial, and MLC actions, with commands or script invocations and artifact paths.
6. Flash and boot results, including serial log paths.
7. Test commands, complete captured-result paths, and measured results.
8. Whether the issue reproduced.
9. Resolution degree: not reproduced / partially reproduced / reproduced / blocked.
10. Root-cause hypothesis.
11. Remaining gaps and recommended next validation.
12. For non-identical lab and customer environments, the local measured result, material differences, and whether a quantitative customer comparison is valid.

For performance issues, distinguish:

- functional failure
- configuration/BIOS knob behavior
- expected architectural tradeoff
- measurement mismatch due to tool version, DIMM population, SNC/directory mode, or OS settings

## Known Example: HSD 14025984558

Issue: cross-NUMA MLC bandwidth on BHS/GNR-SP 2S `2025_WW03`.

Validated run:

```text
control server: lab-control-05 / 192.0.2.53
BKC folder: C:\Users\debug\Desktop\BKC\GNRSP_25WW03
bin: C:\Users\debug\Desktop\BKC\GNRSP_25WW03\REPLACE_WITH_IMAGE.bin
SHA256: CFCF8C0CF65AAEE08D7F344B11EBBCB5EA463504A2478DD6B0F622287C13EBF3
flash: PASS
boot: PASS
MLC v3.11b: all subtests EXIT:0
bandwidth_matrix local: ~116-118 GB/s
bandwidth_matrix remote: ~33-36 GB/s
resolution: partially reproduced / likely Directory Mode Override and RSF behavior
report: out\14025984558\hsd_14025984558_numa_repro_report.md
```

Technical hypothesis from that case:

- `Directory Mode Override` and RSF mode strongly affect cross-NUMA bandwidth.
- `Memory Directory` or `Directory Backed USF` can improve remote access bandwidth.
- `Inclusive RSF` may add snoop invalidate / response traffic when RSF is full, lowering remote 100R bandwidth.
