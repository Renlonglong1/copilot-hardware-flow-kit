# Copilot HSD Hardware Debug Chain - Flow Explanation

Copyright (c) Team PAE FW.  
Author: Li Renlong  
Nickname: longlin

Related draw.io file:

```text
docs\copilot_hsd_hardware_debug_chain.drawio
```

## 1. Purpose

This flow describes the long-term target of using **Copilot CLI + scripts** to connect two validated workflows:

1. HSD issue intake, article extraction, AI summary, and initial issue analysis.
2. Internal hardware reproduction, BIOS flashing, boot-log capture, MLC testing, and result analysis.

The final goal is to improve developer efficiency by allowing Copilot CLI to help read new HSD issues, extract key information, summarize the problem, propose initial hypotheses, and, when needed, drive internal reproduction on matching hardware configurations.

## 2. Current Status

Two standalone flows have already been validated:

| Flow | Status | Key Evidence |
|---|---|---|
| HSD analysis flow | Validated | Article fetch, field extraction, summary, and initial hypothesis generation work |
| Hardware validation flow | Validated | SSH, EM100 flashing, COM3/COM4 boot capture, and MLC baseline work |

The two flows are **not fully linked yet**. The future work is to automatically convert HSD issue information into an internal reproduction plan.

## 3. Diagram Structure

The draw.io diagram is divided into four swimlanes.

### 3.1 HSD / Issue Intake

This lane represents the input source.

Main steps:

1. A new HSD issue or bug appears.
2. Copilot uses `scripts\Invoke-HsdArticleFetch.ps1` to fetch the article.
3. The helper extracts useful fields such as title, status, description, comments, customer blog history, attachments, platform, component, and configuration hints.

Important validated fallback:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <article-id> -ForceCurlDirect
```

Use this when Python API access returns generic HTML `403 Access Denied`.

### 3.2 Copilot CLI + AI Reasoning

This lane represents Copilot's reasoning and developer-facing output.

Main steps:

1. Generate a concise issue summary.
2. Identify customer request, symptom, platform, component, and missing information.
3. Produce an initial hypothesis or debug direction.
4. Decide whether internal reproduction is required.

If reproduction is not needed, Copilot can directly provide:

```text
Issue summary + recommendation + missing data request
```

If reproduction is needed, Copilot should generate a reproduction plan based on the HSD configuration.

### 3.3 Portable Flow Kit

This lane represents the reusable knowledge and automation library.

Key parts:

```text
README.md
USER_QUICK_START.md
.github\copilot-instructions.md
docs\*.md
config\hardware-flow.<server>.json
scripts\*.ps1
```

The kit stores:

1. Validated commands.
2. Server-specific configuration.
3. Known pitfalls and recovery rules.
4. HSD extraction logic.
5. Hardware automation scripts.
6. Lessons learned from previous debug sessions.

Important validated lessons:

```text
EM100.exe / Emulator.exe can block smucmd access.
smucmd exit code alone is not enough; inspect output keywords.
Long remote PowerShell commands may fail; copy helper scripts and run powershell -File.
COM3 command markers can be echoed; verify real prompt and saved result files.
HSD Python requests may hit generic 403; use curl --noproxy "*" fallback.
```

### 3.4 Internal Hardware Reproduction

This lane represents the lab-side execution path.

Main steps:

1. Prepare internal hardware server and SSH access.
2. Check DediProg EM100, PowerSplitter, serial ports, and target BIOS image.
3. Power off and flash through `smucmd.exe`.
4. Open COM3/COM4 before power-on.
5. Capture full raw boot logs.
6. Log in to Host OS through COM3.
7. Run MLC baseline and save logs.
8. Feed results back to Copilot for analysis.

Validated one-pass command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

## 4. Critical Rules

### Flash must pass before serial capture

Do not start long COM3/COM4 capture unless EM100 programming has passed.

Flash success requires all of:

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

### HSD credentials must not be stored

Use the user's existing Windows/Kerberos login context. Do not ask for or store:

```text
passwords
cookies
SSO tokens
service tokens
Kerberos ticket contents
SSH private keys
```

### AI output must be evidence-based

Copilot should separate:

```text
Known facts from HSD
Observed evidence from hardware logs
Initial hypothesis
Recommended next action
Unconfirmed assumptions
```

## 5. Future Linkage Plan

The future integration point is between:

```text
HSD extracted configuration
```

and:

```text
internal hardware reproduction config
```

Expected future automation:

1. Parse HSD article fields.
2. Identify platform, CPU, BIOS/IFWI, DIMM, BMC, OS, test case, and log requirements.
3. Generate or select a matching `config\hardware-flow.<server>.json`.
4. Run the proper hardware validation script.
5. Analyze COM3/COM4/MLC logs.
6. Produce a developer-facing report.

Target final output:

```text
HSD issue summary
Initial suspected root cause
Internal reproduction plan
Execution result
Log evidence
Recommended fix or next debug step
```

## 6. How to Use the Diagram

Open the draw.io file:

```text
docs\copilot_hsd_hardware_debug_chain.drawio
```

Use it as:

1. A communication diagram for explaining the long-term Copilot-assisted debug workflow.
2. A migration reference when setting up a new Copilot environment.
3. A design baseline for future automation work that connects HSD analysis with hardware reproduction.

## 7. Ownership

```text
Team: Team PAE FW
Author: Li Renlong
Nickname: longlin
Purpose: Copilot-assisted HSD analysis, hardware reproduction, debug automation, and knowledge reuse
```

This document and the related draw.io file are intended for authorized internal development and validation use only.
