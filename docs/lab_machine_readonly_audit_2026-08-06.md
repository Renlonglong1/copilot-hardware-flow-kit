# Read-Only Lab-Machine Audit — 2026-08-06

This is a capability inventory, not a run authorization. The audit did **not** flash,
power-cycle, reset, install, copy, delete, open a serial port, or access an attached
host OS. Do not infer a machine's hardware wiring or platform state from the presence
of a CLI executable.

## SSH Policy Used

Each attempted connection used a dedicated local SSH identity and dedicated trusted
host-key file. The local paths are intentionally not recorded in Git. The policy was:

```text
BatchMode=yes; ConnectionAttempts=1; IdentitiesOnly=yes;
PasswordAuthentication=no; KbdInteractiveAuthentication=no;
PreferredAuthentications=publickey; StrictHostKeyChecking=yes;
UserKnownHostsFile=<dedicated local file>; GlobalKnownHostsFile=NUL
```

Never use `StrictHostKeyChecking=no`, accept a new key during an audit, use a password,
or fall back to default SSH identities.

## Results

| Machine | Address / platform | Audit result | Safe conclusion |
|---|---|---|---|
| `dbgsh05` | `10.239.84.53`, GNR/BHS | Reachable; SSH exit 0 | Tools and inventory evidence below were read successfully. |
| `dbgsh12` | `10.239.84.44`, DMR | **Not audited** | The dedicated known-hosts file had no trusted entry. The reported-down state is **unverified**; no connection attempt was made. |
| `dbgsh16` | `10.238.12.230`, DMR | Reachable; SSH exit 0 | Tools and inventory evidence below were read successfully. |

## Evidence

### dbgsh05

| Area | Read-only evidence |
|---|---|
| OS | Windows 11 Enterprise |
| EM100 / `smucmd` | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe`, file version `0.5.9.5`; `-h` returned help. DediProg Emulator Pro PnP driver status was `OK`. |
| PowerSplitter | `C:\tools\PowerSplitter\PowerSplitterCL.exe`, file version `1.0.0.0`; `psconfig.xml` exists and `/?` returned help. |
| COM PnP mapping | COM3 = Silicon Labs Dual CP210x Enhanced COM Port; COM4 = Silicon Labs CP210x USB-to-UART Bridge; both PnP status `OK`. No port was opened; any CPU/BMC role assignment is historical and was not revalidated electrically. |
| BKC / CScripts | BKC root `C:\Users\debug\Desktop\BKC\uPLR2` exists with sampled BHS 64 MiB images. CScripts roots `2431.6000` and `GNR2515.6001` exist. Python is `3.10.10`. |
| MLC | Saved Windows-side evidence at `flow_logs\mlc_20260623_094805\mlc_summary.txt` identifies attached-host result directory `/root/mlc_v3.11b/copilot_mlc_results_20260623_094808` and seven stages marked `DONE`. The attached host OS was not contacted, so current MLC availability is unverified. |

### dbgsh16

| Area | Read-only evidence |
|---|---|
| OS | Windows 11 Enterprise LTSC |
| EM100 / `smucmd` | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe`, file version `0.5.9.5`; `-h` returned help. DediProg Emulator Pro PnP driver status was `OK`. The expected `...\EM100\help.pdf` is absent. |
| PowerSplitter | CLI copies at `C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe` and `C:\SVShare\user_apps\PowerSplitter\PowerSplitterCL.exe`, both file version `1.0.0.0`; `/?` returned help. `psconfig.xml` is present. |
| COM PnP mapping | COM27/28/29/30 are FTDI USB serial PnP devices, all status `OK`. The observed USB-interface mapping is B/A/D/C respectively. No port was opened, and CPU/BMC role mapping remains unverified. |
| BKC / CScripts | BKC root exists with `DMR_26WW20`, `DMR_26WW24`, `DMR_26WW28`, and `DMR_37D18`; sampled images included 64 MiB and 128 MiB files. CScripts roots include revisions `2550_2000`, `2615_2000`, and legacy `CScripts`; Python is `3.10.9`. |
| DMR command wrappers | `dmr_clearcmos.exe --help` and `dmr_runsetupenv.exe --help` returned help. **Do not invoke these in a filesystem-read-only audit:** `dmr_runsetupenv.exe --help` created an empty `C:\Users\debug\PDUApiUtils_2026-08-06_11-17-37.log`. It was not removed. |
| MLC | No nonintrusive, saved MLC evidence was found; status remains unverified. |

## AI Discovery and Run Guidance

1. Read `config\lab-machine-inventory.json` and this audit before selecting a
   control server. Treat `dbgsh12` as unavailable until an administrator provides a
   verified dedicated host-key entry and the audit is repeated.
2. For a **read-only refresh**, use
   `scripts\Get-LabMachineReadOnlyInventory.ps1` with a locally managed identity and
   known-hosts file. It only reads file/PnP metadata and deliberately does not run
   vendor `--help` commands or open COM ports.
3. Before any state-changing action, stop and obtain explicit authorization for the
   exact target, image, power/serial operation, and maintenance window. Then perform
   a separate device/wiring, BKC-family, and serial-role validation. This audit is not
   sufficient authorization or evidence for flashing/power control.
4. For MLC, require saved evidence from the attached host OS or a separately
   authorized access method. A Windows control-server path alone does not establish
   MLC availability.
5. If a separately authorized serial capture reports `Access to the port '<COMx>' is
   denied`, check for a running MobaXterm serial session first. Close only the
   confirmed MobaXterm PID, retry the port open, and do not power on until all
   required capture ports are ready.

Example read-only refresh (paths are local and must not be committed):

```powershell
.\scripts\Get-LabMachineReadOnlyInventory.ps1 `
  -HostName '10.239.84.53' -UserName 'debug' `
  -IdentityFile "$HOME\.ssh\<dedicated-identity>" `
  -KnownHostsFile "$HOME\.ssh\<dedicated-known-hosts>"
```

## Blockers

1. `dbgsh12` cannot be classified as reachable or down under strict host-key policy
   until its trusted host key is provisioned out of band.
2. `dbgsh16` serial roles, EM100 wiring, and PowerSplitter device readiness are
   unverified. Its MLC availability is also unverified.
