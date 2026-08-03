# BHS uPLR2 Robust Full Hardware Flow

This document describes the validated end-to-end flow for programming the BHS uPLR2 BIOS image through DediProg EM100, controlling board power through PowerSplitter, and validating boot through COM3/COM4 serial logs.

The key rule is: **do not start long serial capture unless the EM100 programming step has already passed**.

## Environment

| Item | Value |
|---|---|
| Server | `debug@10.239.84.53` |
| Hostname | `DBGSH05` |
| DediProg CLI | `C:\Program Files (x86)\DediProg\Emulator\smucmd.exe` |
| DediProg GUI processes to avoid | `EM100.exe`, `Emulator.exe` |
| PowerSplitter CLI | `C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe` |
| Chip | `MX66U1G45G` |
| BIN | `C:\Users\debug\Desktop\BKC\uPLR2\BHSDCRB1.IPC.3545.P03.2511062122_GB01000405_GA10000680_SC03000393_RB0A000133_SP_IP_Clean_Debug_PRQ_DAM_Enabled_1.bin` |
| BIN size | `67108864` bytes |
| BIN SHA256 | `04D1BC0DDB572504FF1D4E54E29C2733C5E702306D68D1D39EC6E17DD8B77587` |
| COM3 | GNR CPU serial log |
| COM4 | BMC serial console/log |
| Serial settings | `115200, 8 data bits, no parity, 1 stop bit` |

## Validated Result

Latest validated run:

```text
C:\Users\debug\Desktop\flow_logs\20260623_093722
```

Result:

```text
FLASH_OK=True
FLOW_OK=True
COM3_BYTES=1259493
COM4_BYTES=70548
```

COM3 reached:

```text
CentOS Stream 9
gnr-bkc login
```

COM4 reached:

```text
U-Boot
Linux
OpenBMC
login:
```

## High-Level Flow

1. SSH to the Windows server.
2. Precheck DediProg / EM100 state.
3. If GUI tools are using EM100, close them or report the conflict.
4. Stop EM100 emulation.
5. Turn all PowerSplitter outputs off.
6. Program the BIN into EM100 and verify it.
7. If programming fails, diagnose immediately and do not capture serial logs.
8. If programming succeeds, open COM3 and COM4 log files.
9. Turn all PowerSplitter outputs on.
10. Capture full raw COM3/COM4 logs for about 10 minutes.
11. Analyze only the saved logs.
12. If MLC is requested, log in on COM3 and verify saved MLC result logs contain `EXIT:0`.

## Validated One-Pass Wrapper

Use this local wrapper from the kit root when migrating or validating DBGSH05:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\hardware-flow.dbgsh05.json -CloseGuiConflicts -RunMlc
```

It is safer than hand-built long SSH commands because it copies small helper scripts to the remote `flow_logs` directory and runs them with `powershell -File`.

## Critical Rule: Fail Fast Before Serial Capture

Programming failure is a blocking error. If `smucmd` fails, stop immediately and diagnose. Do **not** wait 10 minutes for serial logs.

Treat these as failure keywords:

```text
No device is connected!
Verify Fail
Authentication Fail
Download failed
ERROR
```

The programming step must include all of these success keywords:

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

## Precheck

Run these checks before programming:

```powershell
$smu = 'C:\Program Files (x86)\DediProg\Emulator\smucmd.exe'
$bin = 'C:\Users\debug\Desktop\BKC\uPLR2\BHSDCRB1.IPC.3545.P03.2511062122_GB01000405_GA10000680_SC03000393_RB0A000133_SP_IP_Clean_Debug_PRQ_DAM_Enabled_1.bin'

Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'EM100|Emulator|smucmd|DediProg' -or $_.CommandLine -match 'EM100|Emulator|smucmd|DediProg' } |
  Select-Object ProcessId,Name,CommandLine

Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.Name -match 'DediProg|EM100' -or $_.DeviceID -match 'VID_04B4|VID_04D8' } |
  Select-Object Name,Status,DeviceID

Get-Item -LiteralPath $bin | Select-Object FullName,Length,LastWriteTime
Get-FileHash -LiteralPath $bin -Algorithm SHA256
& $smu -c
```

Expected useful signs:

```text
DediProg Emulator Pro driver    OK
Device 1 (EM143479)
```

If `smucmd -c` says the command cannot execute because the emulator is in Emulation mode, that is acceptable. It means the device is visible. The next `--stop` step should move it to STOP mode.

## GUI Conflict Handling

If `smucmd` returns `No device is connected!` while Windows still shows `DediProg Emulator Pro driver OK`, check for GUI processes:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'EM100|Emulator' -or $_.CommandLine -match 'EM100|Emulator' } |
  Select-Object ProcessId,Name,CommandLine
```

Known issue:

```text
Emulator.exe
EM100.exe
```

These GUI processes can make `smucmd` unable to access EM100. Close them, then recheck:

```powershell
& 'C:\Program Files (x86)\DediProg\Emulator\smucmd.exe' -c
```

After closing the GUI process, the expected recovery signal is:

```text
Device 1 (EM143479)
```

Validated 2026-06-23 recovery: `EM100.exe` was running, USB still showed `DediProg Emulator Pro driver OK`, and `smucmd -c` printed `No device is connected!`. Closing `EM100.exe` restored `Device 1 (EM143479)`.

## Programming Phase

Use this order:

```powershell
$power = 'C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe'
$smu = 'C:\Program Files (x86)\DediProg\Emulator\smucmd.exe'
$bin = 'C:\Users\debug\Desktop\BKC\uPLR2\BHSDCRB1.IPC.3545.P03.2511062122_GB01000405_GA10000680_SC03000393_RB0A000133_SP_IP_Clean_Debug_PRQ_DAM_Enabled_1.bin'
$chip = 'MX66U1G45G'

& $smu --stop
& $power poweroff
Start-Sleep -Seconds 2
& $smu --stop --set $chip -d $bin -v --start
```

Expected successful programming output:

```text
Device 1 (EM143479) :
Stop Emulator.
Emulator is in STOP mode now.
Chip 1 MX66U1G45G is set.
VCC 1.8V is applied!
Download ...bin to emulator.
Download Complete
Verify Pass. Checksum is the same.
Start Emulator.
Emulator is in Emulation mode.
Ready to boot your system now.
Authentication Pass
```

Only after this point should the flow continue to power-on and serial capture.

## Failure Diagnosis and Auto-Recovery Policy

If programming fails:

1. Stop immediately.
2. Save the `smucmd` output.
3. Check DediProg USB device status.
4. Check for `EM100.exe` / `Emulator.exe` GUI processes.
5. If GUI processes exist, close them and retry `smucmd -c` / `smucmd --stop`.
6. Retry programming at most 1 or 2 times.
7. If it still fails, terminate the flow and report the failure reason.

Common failure mapping:

| Symptom | Likely cause | Action |
|---|---|---|
| `No device is connected!` and USB device exists | GUI process owns EM100 or EM100 driver state is stale | Close `EM100.exe` / `Emulator.exe`, retry `smucmd -c`, then retry programming |
| `No device is connected!` and USB device missing | USB/EM100 not connected or driver issue | Stop flow; ask user to check USB/device |
| `Verify Fail` | Downloaded content does not match file | Stop flow; check bin, chip type, EM100 stability |
| `Authentication Fail` | EM100/auth/device state issue | Stop flow; recheck device and DediProg state |
| `smucmd` hangs | Tool or driver stuck | Terminate stuck `smucmd`, recheck device, retry once |

## Serial Capture Phase

Only start this after programming succeeds.

1. Open COM3 and COM4 first.
2. Power on the board.
3. Save raw serial logs for about 10 minutes.
4. Analyze logs after capture completes.

Power on:

```powershell
& 'C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe' poweron
```

Recommended automation scripts:

```text
scripts\Capture-SerialPort.ps1
scripts\Invoke-RemoteBootCapture.ps1
```

Copy these helpers to the remote `flow_logs` directory and run `Invoke-RemoteBootCapture.ps1` with `powershell -File`. Avoid very long `-EncodedCommand` payloads; Windows/SSH command length can fail before the remote script starts.

Recommended output files:

```text
C:\Users\debug\Desktop\flow_logs\YYYYMMDD_HHMMSS\COM3_GNR_CPU_full_10m.log
C:\Users\debug\Desktop\flow_logs\YYYYMMDD_HHMMSS\COM4_BMC_full_10m.log
```

Why capture first and analyze later:

- COM3 may be silent for a while before GNR CPU logs appear.
- Full boot can take around 10 minutes.
- Early analysis can produce false failures.
- Raw logs are needed for later review by humans or other AI agents.

## Serial Validation Signals

COM3 / GNR CPU success signals:

```text
PROGRESS CODE
Pass PeiPipeSlaveInit
BIOS
DXE
Boot
CXL Stack
ScktId
Training
CentOS Stream 9
gnr-bkc login
```

COM4 / BMC success signals:

```text
U-Boot
Linux
OpenBMC
bmc-mac...
login:
```

Final flow success requires:

```text
FLASH_OK=True
POWERON_EXIT=0
COM3 log has content
COM4 log has content
COM3 reaches gnr-bkc login or equivalent OS boot signal
COM4 reaches BMC login or equivalent OpenBMC signal
```

## Recommended Log Directory Layout

Each run should create a unique timestamped directory:

```text
C:\Users\debug\Desktop\flow_logs\YYYYMMDD_HHMMSS\
```

Recommended files:

```text
00_process_check.txt
00_smucmd_stop.txt
01_poweroff.txt
02_smucmd_flash.txt
03_poweron.txt
bin_hash.txt
COM3_GNR_CPU_full_10m.log
COM4_BMC_full_10m.log
summary.txt
analysis.txt
```

## Known Good Run

The following runs completed successfully:

```text
C:\Users\debug\Desktop\flow_logs\20260623_093722
C:\Users\debug\Desktop\flow_logs\20260617_150451
```

Important results:

```text
FLASH_OK=True
POWERON_EXIT=0
COM3_BYTES=1259493
COM4_BYTES=70548
FLOW_OK=True
```

Key programming evidence:

```text
Download Complete
Verify Pass. Checksum is the same.
Emulator is in Emulation mode.
Authentication Pass
```

Key COM3 evidence:

```text
CentOS Stream 9
Kernel 6.6.0-gnr.bkc.6.6.27.2.41.x86_64
gnr-bkc login:
```

Key COM4 evidence:

```text
U-Boot
Linux
OpenBMC
bmc-mac0007e9346b7c login:
```

## COM3 OS Login and Command Interaction Validation

Validated run:

```text
C:\Users\debug\Desktop\flow_logs\20260617_154554
```

After successful EM100 programming and power-on, COM3 eventually reaches the host OS login prompt:

```text
gnr-bkc login:
```

Validated login method:

```text
username: root
password: dcpae_123
```

After login, the following commands were tested successfully through COM3 serial interaction:

```bash
lscpu
lsmem
ip addr
```

Validated result:

```text
LOGIN_PROMPT_FOUND=True
PASSWORD_PROMPT_FOUND=True
ROOT_SHELL_FOUND=True
LSCPU_OK=True
LSMEM_OK=True
IP_ADDR_OK=True
OS_INTERACTION_OK=True
```

Saved logs:

```text
COM3_GNR_CPU_boot_and_os_interaction_retry.log
os_interaction_retry.txt
summary.txt
```

Operational note: if COM3 returns `Access to the port 'COM3' is denied`, do not power on yet. Stop and diagnose the serial-port conflict first. In the validated run, retrying COM3 open after the handle was released succeeded, then the flow continued from the already successful flash state.

## MLC Validation After Boot

Validated MLC result directories:

```text
/root/mlc_v3.11b/copilot_mlc_results_20260623_094808
/root/mlc_v3.11b/copilot_mlc_results_20260623_094928
```

Validated logs:

```text
01_idle_latency.log:EXIT:0
02_latency_matrix.log:EXIT:0
03_bandwidth_matrix.log:EXIT:0
04_peak_injection_bandwidth.log:EXIT:0
05_loaded_latency.log:EXIT:0
06_c2c_latency.log:EXIT:0
```

Automation caution: serial command echo can contain the same marker string that the script is waiting for. Do not report MLC success only because a marker appeared; wait for the real root shell prompt and verify saved host log files contain `EXIT:0`.
