---
name: bhs-hardware-flow
description: "Use when: running BHS uPLR2 hardware flows, DediProg EM100 smucmd programming, PowerSplitter power cycling, COM3/COM4 serial log capture, or robust flash-boot validation on DBGSH05 or migrated servers."
---

# BHS Hardware Flow Skill

Use this skill to run or reason about the BHS uPLR2 robust hardware flow.

## Required Reading

Before acting, read:

1. `docs\bhs_uplr2_robust_full_flow.md`
2. `config\hardware-flow.dbgsh05.json`
3. `docs\emulator_powersplitter_cli_notes.md`

## Operating Contract

1. Never start 10-minute serial capture until the flash step has succeeded.
2. Flash success requires all of:
   - `Download Complete`
   - `Verify Pass`
   - `Emulator is in Emulation mode`
   - `Authentication Pass`
3. Flash failure is blocking. Diagnose immediately.
4. If `No device is connected!` appears, check for `EM100.exe` / `Emulator.exe` GUI processes and DediProg USB status.
5. If recoverable, close the GUI conflict and retry once or twice.
6. If not recoverable, terminate and report the reason, logs, USB status, and process state.
7. Save raw COM3/COM4 logs first, then analyze them.
8. Prefer `scripts\Invoke-BhsUplr2ValidatedFlow.ps1` for one-pass flash, boot capture, and optional MLC validation.
9. Do not trust marker strings echoed by the COM3 shell; verify saved MLC result logs contain `EXIT:0`.
10. When the lab machine, DIMM/topology, BIOS settings, OS, or tool version differs from the customer environment, run the feasible issue-relevant test and report the measured local result. Do not present it as quantitatively identical to the customer result; identify the differences and classify any incomplete match as partial reproduction.

## Default Flow

```text
precheck
-> smucmd --stop
-> PowerSplitter poweroff
-> smucmd --stop --set <chip> -d <bin> -v --start
-> if flash failed: diagnose/recover or terminate
-> if flash succeeded: open COM3/COM4
-> PowerSplitter poweron
-> capture COM3/COM4 raw logs for 10 minutes
-> analyze saved logs
```

## Default Evidence to Report

Report:

- log directory
- bin path and SHA256
- `FLASH_OK`
- `FLOW_OK`
- COM3 byte count and key boot signal
- COM4 byte count and key BMC signal
- local test result and material lab/customer environment differences
- failure diagnosis if any

## Default Known Good Values

```text
server: debug@10.239.84.53
chip: MX66U1G45G
COM3: GNR CPU
COM4: BMC
serial: 115200 8N1
known good log: C:\Users\debug\Desktop\flow_logs\20260617_150451
latest validated log: C:\Users\debug\Desktop\flow_logs\20260623_093722
```
