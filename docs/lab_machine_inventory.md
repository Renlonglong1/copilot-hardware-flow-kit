# Lab Machine Inventory and Selection Rules

This reference is the portable source of truth for selecting a control server after IPS/HSD extraction. The machine-readable form is `config\lab-machine-inventory.json`.

## Platform Alignment

| Control server | SSH | Platform | Select for | Do not select for |
|---|---|---|---|---|
| `dbgsh05` | `debug@10.239.84.53` | GNR / GNR-SP / BHS | GNR/BHS diagnosis, flashing, boot capture, and validated MLC | DMR/Oak Stream images or tests |
| `dbgsh12` | `debug@10.239.84.44` | DMR / Oak Stream / OKS | DMR diagnosis, flashing, power control, CScripts | GNR/BHS images or tests |
| `dbgsh16` | `debug@10.238.12.230` | DMR / Oak Stream / OKS | DMR diagnosis, local DMR BKC and CScripts work | Flashing or power control until those capabilities are installed and verified |

Never choose a machine solely because a BKC version string appears compatible. First match the IPS/HSD platform model and family, then select the machine and BKC image.

## Verified Inventory

### dbgsh05 - GNR/BHS

| Item | Status / path |
|---|---|
| BKC root | `C:\Users\debug\Desktop\BKC` - 208 `.bin` files observed |
| Representative BKC folders | `GNRSP_25WW03`, `GNRSP_25WW16`, `GNRSP_43D53`, `GNRSP_MR2`, `uPLR2`, `uPLR4` |
| EM100 flashing | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe` |
| Power control | `C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe` |
| Serial | COM3 (GNR CPU), COM4 (BMC), 115200 8N1 |
| CScripts | `C:\Users\debug\Desktop\CScripts\686308 BHS CScripts 2431.6000`; `C:\Users\debug\Desktop\CScripts\686308_BHS_CScripts_GNR2515.6001` |
| MLC | Validated on the attached GNR host OS at `/root/mlc_v3.11b`; use COM3 only after a successful flash and boot |
| Logs | `C:\Users\debug\Desktop\flow_logs` |

Use `config\hardware-flow.dbgsh05.json` and `scripts\Invoke-BhsUplr2ValidatedFlow.ps1` for validated GNR flow execution. Flash success must precede any long serial capture.

### dbgsh12 - DMR/Oak Stream

| Item | Status / path |
|---|---|
| BKC root | `C:\Users\debug\Desktop\BKC` - 43 `.bin` files observed |
| BKC families | `35D23`, `up982_bkc`, DMR `30.D59`, `30.D43`, `29.D60`, and WW46 candidates |
| Detailed BKC index | `config\bkc-remote-inventory.dbgsh05.json` and `docs\bkc_remote_inventory_dbgsh05.md`; these are legacy filenames, but their host is `10.239.84.44` / `dbgsh12` |
| EM100 flashing | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe` |
| Power control | `C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe` |
| Serial | Historical mapping: COM8, COM9, COM10, COM11; confirm role mapping before capture |
| CScripts | `C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000\cscripts` |
| MLC | Not yet inventoried on the attached DMR host OS; verify before scheduling |

The CScripts reference is `docs\cscripts_oak_stream_usage.md`. For normal IFWI selection, prefer a platform-matched 128 MB full image unless the task explicitly requires a split image.

### dbgsh16 - DMR/Oak Stream

| Item | Status / path |
|---|---|
| BKC root | `C:\Users\debug\Desktop\BKC` |
| BKC folders | `DMR_26WW24`, `DMR_26WW28`, `DMR_37D18` |
| CScripts | `C:\Users\debug\Desktop\CScripts\821387_Oak_Stream_CScripts_Rev_2615_2000\cscripts` |
| Serial | COM27, COM28, COM29, COM30; confirm CPU/BMC role mapping before capture |
| EM100 CLI | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe`; `-h` verified, but USB device and flash wiring are unverified |
| PowerSplitter CLI | `C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe`; copied from `dbgsh12`, `/?` verified, but hardware wiring is unverified |
| MLC | Not yet inventoried on the attached DMR host OS; verify before scheduling |

CScripts and the primary PowerSplitter CLI were copied from `dbgsh12`. CScripts was validated by import plus `cscripts_api.py --help`; both local control CLIs were validated only through their help commands. Do not use `dbgsh16` for flash or power actions until the corresponding USB/device and wiring prechecks pass.

## Automated Selection Procedure

1. Extract the customer platform/model, socket topology, BKC version, and requested test from IPS/HSD.
2. Match platform/model against `platformAliases` in `config\lab-machine-inventory.json`.
3. Reject an unknown or conflicting family instead of guessing.
4. For a flashing request, require `flashControl: true`, then match the BKC image's family, version, socket count, and size.
5. For MLC, require an explicit MLC availability check on the attached host OS.
6. Save the selected machine, BKC path/hash, capability checks, and evidence in the reproduction report.

## Refresh Policy

Refresh this inventory after any change to a control server's BKC root, serial mapping, EM100/PowerSplitter installation, CScripts revision, or attached host OS. Do not infer a capability from another machine in the same platform family.
