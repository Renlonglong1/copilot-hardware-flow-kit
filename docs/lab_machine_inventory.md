# Lab Machine Inventory and Selection Rules

This reference is the portable source of truth for selecting a control server after IPS/HSD extraction. The machine-readable form is `config\lab-machine-inventory.json`.

## Platform Alignment

| Control server | SSH | Model / platform | Select for | Do not select for |
|---|---|---|---|---|
| `dbgsh05` | `debug@10.239.84.53` | GNR / GNR-SP / BHS | GNR/BHS diagnosis and read-only local tool discovery; use state-changing tools only with separate approval | DMR/Oak Stream images or tests |
| `dbgsh12` | `debug@10.239.84.44` | DMR / Oak Stream / OKS | **Not selectable**: strict host-key trust is not provisioned and reachability is unverified | Any run or capability assumption |
| `dbgsh16` | `debug@10.238.12.230` | DMR / Oak Stream / OKS | DMR diagnosis, local DMR BKC and CScripts discovery | Flashing, power control, or serial capture without separate approval and readiness checks |

Never choose a machine solely because a BKC version string appears compatible. First match the IPS/HSD platform model and family, then select the machine and BKC image.

The authoritative current evidence and the strict SSH policy are in
`docs\lab_machine_readonly_audit_2026-08-06.md`. It supersedes historical
availability claims below where they conflict.

## Verified Inventory

### dbgsh05 - GNR/BHS

| Item | Status / path |
|---|---|
| BKC root | `C:\Users\debug\Desktop\BKC` - 208 `.bin` files observed |
| Representative BKC folders | `GNRSP_25WW03`, `GNRSP_25WW16`, `GNRSP_43D53`, `GNRSP_MR2`, `uPLR2`, `uPLR4` |
| EM100 flashing | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe` |
| Power control | `C:\tools\PowerSplitter\PowerSplitterCL.exe` |
| Serial | COM3 (Silicon Labs Dual CP210x Enhanced), COM4 (Silicon Labs CP210x USB-to-UART Bridge); both PnP status `OK`. No port was opened; historical CPU/BMC role labels and serial settings require revalidation before use. |
| CScripts | `C:\Users\debug\Desktop\CScripts\686308 BHS CScripts 2431.6000`; `C:\Users\debug\Desktop\CScripts\686308_BHS_CScripts_GNR2515.6001` |
| MLC | Saved evidence records a completed run on the attached GNR host OS at `/root/mlc_v3.11b`; current availability was not checked and must be revalidated before use |
| Logs | `C:\Users\debug\Desktop\flow_logs` |

Use `config\hardware-flow.dbgsh05.json` and `scripts\Invoke-BhsUplr2ValidatedFlow.ps1` for validated GNR flow execution. Flash success must precede any long serial capture.

### dbgsh12 - DMR/Oak Stream

The 2026-08-06 audit did not connect: no dedicated trusted host key was available
locally. Its reported-down condition is therefore unverified, not confirmed. Treat
all older BKC, EM100, PowerSplitter, and COM-path entries for this machine as
historical only; do not execute against them or rely on them for selection.

### dbgsh16 - DMR/Oak Stream

| Item | Status / path |
|---|---|
| DMR CLI | `pysvext-diamondrapids-execution` 1.23.0.600 installs `C:\Python310\Scripts\dmr_clearcmos.exe` and `dmr_runsetupenv.exe`; only `--help` was run, and both returned exit 0. No ClearCMOS, power-cycle, BMC, or environment-setup operation was requested. `dmr_runsetupenv.exe --help` nevertheless initialized its logger and created an empty `PDUApiUtils_*.log`; use static argparse inspection instead when filesystem read-only behavior is mandatory. |
| BKC root | `C:\Users\debug\Desktop\BKC` |
| BKC folders | `DMR_26WW20`, `DMR_26WW24`, `DMR_26WW28`, `DMR_37D18` |
| CScripts | Revisions `2550_2000`, `2615_2000`, and legacy `CScripts\cscripts` are present. Primary path: `C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000\cscripts`; `cscripts_api.py --help` passed with Python 3.10.9 and lists DMR ingredients. |
| Serial | COM27 = FTDI B/MI_01, COM28 = FTDI A/MI_00, COM29 = FTDI D/MI_03, COM30 = FTDI C/MI_02. All four PnP devices report OK. No port was opened; CPU/BMC role mapping remains unverified. |
| EM100 CLI | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe`, file version 0.5.9.5; `-h` passed and the DediProg Emulator Pro USB driver is present. The Emulator GUI was running, and flash wiring/readiness was not tested. |
| PowerSplitter CLI | Version 1.0.0.0 at both `C:\SVShare\user_apps\PowerSplitter\PowerSplitterCL.exe` and the Desktop copy; `/?` passed for both. Their identical `psconfig.xml` files declare one connected device and port control enabled. The active GUI uses the `C:\SVShare` copy, but the CLI exposes no read-only status command, so USB/wiring/device readiness remains unverified. |
| Remote shell | Default OpenSSH shell is `cmd.exe`; its default `PATH` cannot resolve `powershell`. Explicit `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` works (5.1.26100.8875). |
| MLC | Not yet inventoried on the attached DMR host OS; verify before scheduling |

Read-only validation was refreshed on 2026-08-06. No flash, power, reset, cycle,
serial I/O, or configuration command was issued. Do not use `dbgsh16` for flash or
power actions until the corresponding device/wiring prechecks pass under a separately
approved state-changing plan.

## Automated Selection Procedure

1. Extract the customer platform/model, socket topology, BKC version, and requested test from IPS/HSD.
2. Match platform/model against `platformAliases` in `config\lab-machine-inventory.json`.
3. Reject an unknown or conflicting family instead of guessing.
4. For a flashing request, require a capability status that explicitly supports the
   intended operation, explicit user authorization, and then match the BKC image's
   family, version, socket count, and size.
5. For MLC, require an explicit MLC availability check on the attached host OS.
6. Save the selected machine, BKC path/hash, capability checks, and evidence in the reproduction report.

## Refresh Policy

Refresh this inventory after any change to a control server's BKC root, serial mapping, EM100/PowerSplitter installation, CScripts revision, or attached host OS. Do not infer a capability from another machine in the same platform family.
