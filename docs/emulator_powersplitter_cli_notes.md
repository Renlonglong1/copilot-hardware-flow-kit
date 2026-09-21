# EM100 and PowerSplitter operation boundary

The tools and drivers are not bundled. Obtain approved vendor installations and
set their actual paths in the ignored local hardware profile.

Prefer `Invoke-BhsUplr2ValidatedFlow.ps1` over piecing together raw commands.
`Invoke-Emulator.ps1` and `Invoke-PowerSplitter.ps1` are hardware-affecting wrappers;
their presence does not authorize operating any attached device.

Verify the chip and expected EM100 device identifier. Flash exit code alone is
insufficient: the four required success messages in the robust-flow guide must
all be present. A failure must stop the subsequent power-on/capture/test chain.

Only close confirmed conflicting GUI processes by PID, with resource-owner
approval. Do not issue broad process-name kills or alter another user's run.
