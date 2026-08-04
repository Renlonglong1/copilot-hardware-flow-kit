---
name: bios-analyze-log
description: "Decode BIOS Enhanced Warning Log (EWL), IPSD, and RC Fatal error codes from logs. Groups errors by type showing affected Socket/Channel/DIMM/Rank. Supports decoding individual codes and analyzing full BIOS logs. Multi-platform: EGS (EagleStream), BHS (BirchStream), OKS (OakStream). Use for BIOS debugging, memory training failures, firmware errors. Trigger phrases: RC_FATAL_ERROR, FATAL ERROR, Enhanced warning, ERROR: C8."
---

# BIOS Analyze Log

Decode BIOS error codes from Intel firmware logs. Supports EWL (Enhanced Warning Log), IPSD (Intel Platform Service Provider), and RC Fatal errors. Groups identical errors and shows exactly which hardware components are affected.

**Supported platforms:** EGS (EagleStream / ServerGen2), BHS (BirchStream / ServerGen3), OKS (OakStream / ServerGen4).

## When to Use This Skill

Activate this skill when any of the following appear:

- A BIOS log with Enhanced Warning Log (EWL), IPSD, or RC Fatal errors
- Questions about decoding BIOS error codes (e.g., "What does 0x29/0x15 mean?")
- Requests to analyze memory training, PCIe, CPU stepping, or firmware initialization failures
- Need to map errors to hardware topology (Socket/Channel/DIMM/Rank)
- Requests to summarize repeated errors with counts and checkpoints

## Workflow

Follow these steps in order:

1. **Identify the platform — always ask, never assume**
   - You MUST ask the user to confirm the platform before running the decoder. Do not silently pick one.
   - Look for clues in the filename or log content to determine which option to mark as `recommended`:
     - "SPR" / "EMR" → recommend **EGS**
     - "GNR" / "GNRSP" / "SRF" → recommend **BHS**
     - "DMR" / "CWF" / "NVL" → recommend **OKS**
   - Use the `vscode_askQuestions` tool to present a platform picker. Include a brief note about why you're recommending a particular option (e.g., "Detected 'GNRSP' in filename"). Example call:
     ```
     vscode_askQuestions(questions: [{
       header: "Platform",
       question: "Which platform is this log from? (detected 'GNRSP' → BHS)",
       options: [
         { label: "EGS", description: "EagleStream / ServerGen2 — SPR, EMR" },
         { label: "BHS", description: "BirchStream / ServerGen3 — GNR, GNRSP, SRF", recommended: true },
         { label: "OKS", description: "OakStream / ServerGen4 — DMR, CWF, NVL" }
       ],
       allowFreeformInput: false
     }])
     ```
   - Only proceed with `--platform <egs|bhs|oks>` after the user selects a platform
   - Once the platform is confirmed, treat it as the only platform for the rest of this session. Do not mention, compare with, or reference other platforms in the output. The user chose their platform — keep the focus there.
2. **Identify the input**
   - Single code decode (major/minor) or full log analysis
3. **Parse and normalize**
   - Detect supported log formats and extract codes/topology
   - Treat IPSD (`ERROR: C8...`) as in-scope only when the selected platform is OKS
4. **Decode and group**
   - Map codes to names/descriptions and group identical errors
5. **Summarize results**
   - Provide counts, checkpoints, and affected hardware

## Data Source

Use the built-in platform-specific databases in this skill:

| Platform | EWL Database | RC Fatal Database | IPSD Database |
|----------|-------------|-------------------|---------------|
| EGS | `references/egs/ewl_codes_database.json` | `references/egs/rc_fatal_errors_database.json` | — |
| BHS | `references/bhs/ewl_codes_database.json` | `references/bhs/rc_fatal_errors_database.json` | — |
| OKS | `references/oks/ewl_codes_database.json` | `references/oks/rc_fatal_errors_database.json` | `references/oks/ipsd_codes_database.json` |

**Note:** IPSD support is OKS-only.

Do not guess or invent codes. If a code is not found, state that the database does not contain it.

## Capabilities

**Error Types Supported:**
- **EWL codes** - Memory training, PCIe, CPU, etc.
- **IPSD codes** - Platform service provider errors (OKS only)
- **RC Fatal codes** - Memory controller fatal errors

**Database Coverage Per Platform:**

| Platform | EWL Majors | EWL Minors | RC Fatal Majors | RC Fatal Minors | IPSD |
|----------|-----------|-----------|----------------|----------------|------|
| EGS | 95 | 261 | 45 | 221 | — |
| BHS | 123 | 378 | 45 | 335 | — |
| OKS | 124 | 412 | 49 | 449 | 23 |

**Features:**
- **Hardware topology** - Shows Socket/Channel/DIMM/Rank for each error
- **Smart grouping** - Groups identical errors with occurrence counts
- **Checkpoint tracking** - Displays BIOS checkpoint codes (Major/Minor)
- **Multiple log formats** - Parses "Enhanced warning", "Error Logged", "ERROR: C8...", "**FATAL ERROR**", "RC_FATAL_ERROR!" formats
- **JSON output** - Machine-readable output with `--json` flag for pipeline use
- **Source references** - Line numbers from Intel firmware headers

## Output Format (Required)

Use this exact structure and keep it compact:

### BIOS Log Summary
- **Unique errors**:
- **Total occurrences**:
- **Formats**:

### Errors
- **#1** `0x.. / 0x..` - **Occurrences**: - **Sockets**: - **HW**: - **Chkpt**: - **Major**: - **Minor**: - **Desc**:

For single-code decode, output:

### Code Decode
- **Code**: `0x.. / 0x..`
- **Major**:
- **Minor**:
- **Description**:

## Quick Start

### Analyze a BIOS Log

```bash
cd scripts
python decode_ewl.py --platform bhs --log /path/to/bios_serial.log
```

**Output example:**
```
### Error #1: `0X0A / 0X05`
**Occurrences:** 24
**Sockets:** S0
**Affected Hardware:**
- Socket 0, Channel 4, DIMM 0, Rank 1
- Socket 0, Channel 5, DIMM 0, Rank 0
- Socket 0, Channel 14, DIMM 0, Rank 1
**Checkpoints:** 0X7B/0X01
**Major Code:** WARN_USER_DIMM_DISABLE
**Minor Code:** WARN_USER_DIMM_DISABLE_POP_POR_VIOLATION
**Description:** USER DIMM DISABLE / POP POR VIOLATION
```

### Decode a Single Code

```bash
python decode_ewl.py --platform egs --code 0x0A --minor 0x05
```

## Log Formats Supported

Automatically detects and parses:

1. **Enhanced warning blocks** (most common):
   ```
   Enhanced warning of type 1 logged:
   Major Warning Code = 0x0A, Minor Warning Code = 0x05,
   Major Checkpoint: 0x7B, Minor Checkpoint: 0x01
   Socket 0, Channel 4, Dimm 0, Rank 1
   ```

2. **Legacy format**:
   ```
   Error Logged: Class Code = 0011, Error Code = 0005, Minor Code = 0026
   ```

3. **IPSD errors**:
   ```
   ERROR: C80000002:V00021002 I0 DE1F3623-038D-42FE-A096-8EAA80C8171D
   ```

4. **FATAL ERROR blocks**:
   ```
   **FATAL ERROR**
   Major Error Code = 0xCD
   Minor Error Code = 0x2C
   Socket = 0
   ```

5. **RC_FATAL_ERROR! file reference**:
   ```
   RC_FATAL_ERROR! ServerSiliconPkg/Mem/MemDecodeGenDdr.c: 741
   ```

6. **Combined RC Fatal code**:
   ```
   RC Fatal Error Code = 0x3000CD2C
   ```

**Output includes:**
- Error codes grouped by type with occurrence counts
- Affected hardware: Socket/Channel/DIMM/Rank
- BIOS checkpoint codes where error occurred
- Decoded names and descriptions
- Example context from log

## Database Sources

**EWL Codes:** `CpRcPkg/Include/Library/EnhancedWarningLogLib.h`
**RC Fatal Codes:** `CpRcPkg/Include/ReferenceCodeFatalErrors.h`
**IPSD Codes:** Built-in definitions for common platform errors

## Files

- **scripts/decode_ewl.py** - Main decoder (`--platform`, `--log`, `--code`, `--json` options)
- **scripts/parse_rc_fatal_errors.py** - Database generator for RC fatal codes
- **scripts/parse_header.py** - Database generator for EWL codes
- **references/egs/** - EGS platform databases (EWL + RC Fatal)
- **references/bhs/** - BHS platform databases (EWL + RC Fatal)
- **references/oks/** - OKS platform databases (EWL + RC Fatal + IPSD)
- **tests/test_decoder.py** - Regression tests (`pytest tests/` to run)

## Updating Databases

Regenerate from Intel firmware headers when needed:

```bash
# Example: regenerate EGS databases
python scripts/parse_header.py <EGS_BIOS>/Intel/CpRcPkg/Include/Library/EnhancedWarningLogLib.h -o references/egs/ewl_codes_database.json
python scripts/parse_rc_fatal_errors.py <EGS_BIOS>/Intel/CpRcPkg/Include/ReferenceCodeFatalErrors.h -o references/egs/rc_fatal_errors_database.json --pretty
```

## Boundaries (Important)

This skill's findings cover **only**:
- EWL (Enhanced Warning Log) codes matched by the database
- IPSD error codes (pattern `ERROR: C8XXXXXXX`) **only when platform is OKS**
- RC Fatal error codes matched by the database
- Explicit `ASSERT_EFI_ERROR` / `ASSERT` lines from the log

**Do not surface as findings:**
- Informational/debug print lines (e.g., `InstallHobData() Guid: ... HobAddress: ...`) — these indicate success, not failure
- Generic `Failed to read ...` or `Error:` strings that do not match the EWL/RC Fatal patterns (and IPSD pattern only for OKS)
- Do not invent or extrapolate codes beyond the databases
- Do not claim root cause or fix; only decode and summarize
- If the log format is unsupported, state the limitation clearly

## Degraded Topology Awareness

When the log indicates a degraded configuration (e.g., 1S operation with UXI port disabled, Socket 1 absent):
- `Failed to read SPD data at Socket:1 ...` errors are **expected** — Socket 1 DIMMs are unreachable
- Mark such entries as `[Expected — degraded config, Socket N absent]` rather than flagging them as failures
- Do not use expected socket errors as evidence for a root cause

## Tone Guidelines

- Be precise and evidence-based
- Prefer concise, structured summaries suitable for sharing in reviews

