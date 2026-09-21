# Approved BHS robust flow

No target is pre-authorized by this distribution. Confirm resource ownership,
platform/image compatibility, hardware configuration and the execution window.
Read the hardware skill and the Chinese handover before operating equipment.

Use `config\local\hardware-flow.json`; do not use a historical lab profile.
Verify tool paths, image, chip, device serial, power device, CPU/BMC ports,
capture duration and log directory.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-SshAccess.ps1 -ConfigPath .\config\local\hardware-flow.json
```

Require `SSH_OK` and verified host identity. The following is an actual hardware
operation, not an installation check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-BhsUplr2ValidatedFlow.ps1 -ConfigPath .\config\local\hardware-flow.json -CloseGuiConflicts -RunMlc
```

The wrapper prechecks the remote environment, powers off, programs EM100,
validates flash output, then captures CPU/BMC boot logs and optionally runs MLC.
Flash success requires all four messages:

```text
Download Complete
Verify Pass
Emulator is in Emulation mode
Authentication Pass
```

A failed flash blocks boot capture and MLC. Preserve failure evidence first.
For device-not-connected failures, inspect USB and confirmed GUI ownership;
terminate only explicitly identified conflicting process IDs when authorized.

Capture raw serial logs before power-on and retain the full observation window.
Check actual boot evidence and saved test result files, not echoed marker text.
Report the image hash, logs, measured result, configuration differences and
whether the requested issue was reproduced, partially reproduced or blocked.
