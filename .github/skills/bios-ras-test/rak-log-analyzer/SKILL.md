---
name: rak-log-analyzer
description: 'Analyze RAK (RAS Automation Kit) test result log packages downloaded from a remote debug machine. Use when the user wants to review, interpret, or summarize RAK test execution results — including PASS/FAIL verdict, assertion failures, CScripts register output, BIOS serial SMM flow, dmesg/OS error records, and SEL logs. Trigger phrases: "analyze rak log", "check test results", "did the test pass", "what happened in the log", "review rak output", "explain rak result", "parse serial log", "check assertion failure", "analyze log package", "phase 3 log review". Can be used standalone (user provides a log folder path) or as Phase 3 after rak-remote-runner completes.'
argument-hint: 'Provide the local log folder path, or leave empty to use the latest download from rak-remote-runner.'
---

# RAK Log Analyzer

Analyze a RAK test result log package and produce a structured PASS/FAIL verdict with
detailed evidence from each log layer.

## Log Package Structure

A RAK log package downloaded by `rak-remote-runner` has this layout:

```
<rak_result_dir>\<case_name>\
├── <case_name>.py_result.log          # Overall RAK verdict (PASS / FAIL / ERROR)
├── <case_name>.py_CscriptsOutput.log  # CScripts stdout — register values, assertions
├── <case_name>.py_SerialOutput.log    # BIOS serial log — SMM flow, RAS handler messages
├── <case_name>.py_dmesg.log           # OS dmesg — kernel error records (extlog, EDAC)
├── <case_name>.py_SEL.log             # SEL log — platform event records
└── <case_name>.py_BMC_cmd.log         # BMC RAS manager log (OOB RAS cases only)
```

Not all files are present in every run. Adapt analysis to what is available.

---

## Step-by-Step Analysis Procedure

### 1. Locate the Log Package

**If called from Phase 3 (after rak-remote-runner):**
- Use `rak_result_dir` and `case_name` from the Phase 2 run.

**If called standalone:**
- Ask the user: "Please provide the path to the RAK log folder."
- Accept either a folder path or a zip archive.

### 2. Read `*_result.log` First

This file contains the top-level verdict from `rak_cui.exe`.

Look for:
- `PASS` / `FAIL` / `ERROR` verdict line
- Case name, execution time, repeat index

Report this immediately as the **headline result**.

### 3. Analyze `*_CscriptsOutput.log`

Scan for:

| Pattern | Meaning |
|---|---|
| `ASSERT FAILED` / `AssertionError` | A `RAK_ASSERT*` call failed — critical |
| `RAK_ASSERT_CSR ... FAILED` | Register value mismatch — show expected vs actual |
| `PASS` / `FAIL` markers from print statements | Step-level result |
| Register `.show()` output (CSR dumps) | Evidence of HW state |
| `ei.mem.injectMemError` confirmation | Injection acknowledged |
| `error.check_mem_errors()` output | Pre/post error state |
| `ras.mem.show_ecc_mode()` table | ECC mode in use |
| `ras.mem.adddc_status_check()` table | ADDDC/VLS region state |
| `retry_rd_err_log_address1` fields | Memory CE log register |
| `copy_in_progress` / `copy_complete` | Sparing status |

### 4. Analyze `*_SerialOutput.log`

Scan for BIOS SMM flow evidence:

| Pattern | Meaning |
|---|---|
| `[imc] memory error handler start` | IMC error handler invoked |
| `[ADDDC]: Main handler start` | ADDDC SMM handler triggered |
| `Action Status Success` / `Status = Success` | BIOS action completed |
| `Action Status Unsupported` / `Status = Unsupported` | BIOS could not handle — may be expected |
| `VlsSparingCopy: Bank` / `VlsSparingCopy: Rank` | Sparing copy type |
| `[ActionOnBankVls]` / `[ActionOnRankVls]` | VLS region action details |
| `SpareCopyCPLMode` | Sparing copy in progress |
| `copy_in_progress (00:00)` → `(01:01)` | Copy state change |
| `ERROR: C00000002:V03071008` | ADDDC-related EFI error code (expected during sparing) |
| `WHEA: Detected Ras Non Standard Error` | WHEA BIOS log (informational) |
| `[GetRRLErrorInfo]` | Retry read log error info decoded by BIOS |
| `RasEventHndlrEntry index` | RAS event handler dispatch |

### 5. Analyze `*_dmesg.log`

Scan for OS-level error records:

| Pattern | Meaning |
|---|---|
| `extlog_mem_event` | Extended error log memory event (acpi_extlog driver) |
| `corrected error` | CE reported to OS |
| `uncorrected error` | UCE — unexpected for CE injection tests |
| `EDAC` | EDAC memory error record |
| `Hardware Error` | Generic kernel hardware error |
| `mce:` | Machine Check Exception entry |

### 6. Analyze `*_SEL.log` (if present)

Look for:
- Memory correctable error events
- Platform event codes matching the injected error type

### 7. Analyze `*_BMC_cmd.log` (OOB RAS cases only)

Look for:
- `RasSpareEventAdddc` — ADDDC event received by BMC
- `RasSpareCopyInProgress` — sparing copy started
- `RasSpareCopyDone` — sparing complete
- `ERR0 Asserted` — error signal asserted to BMC

---

## Output Format

Present findings in this order:

```
## RAK Log Analysis: <case_name>

### Verdict: PASS / FAIL / ERROR

**Execution time:** X minutes
**Repeat:** N/M

---

### CScripts Layer
- [summary of assertion results and key register values]

### BIOS Serial Layer
- [summary of SMM handler flow and sparing actions]

### OS Layer (dmesg)
- [summary of kernel error records]

### SEL / BMC Layer
- [summary if applicable]

---

### Failure Details (if FAIL)
- [exact assertion that failed, expected vs actual, log line]

### Conclusion
- [1-2 sentences on overall test outcome and notable observations]
```

---

## PASS/FAIL Criteria Guidance

| Condition | Verdict |
|---|---|
| `*_result.log` shows PASS and no assertion failures | PASS |
| Any `RAK_ASSERT*` failure in CScripts log | FAIL |
| `rak_cui.exe` exit code non-zero | FAIL / ERROR |
| Expected BIOS SMM handler not triggered | Investigate — may be FAIL |
| `copy_in_progress` never transitions for sparing tests | Investigate |
| OS dmesg shows UCE on a CE-only test | Flag as anomaly |

Do NOT invent pass/fail verdicts. Base the conclusion strictly on log content.

---

## Standalone Invocation

When called without Phase 2 context, ask:

> "Please provide the local path to the RAK log folder (e.g. `C:\source\RAK-AI\rak_results\BHS_SDDC_CE_Injection\`)."

Then proceed with the analysis procedure above.
