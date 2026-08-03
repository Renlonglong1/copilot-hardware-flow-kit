param(
    [string]$Chip,

    [Parameter(Mandatory = $true)]
    [string]$BinFile,

    [switch]$SkipPowerOff,
    [switch]$SkipPowerOn,

    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

if (-not $ConfigPath) {
    $scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $ConfigPath = Join-Path $scriptRoot '..\config\hardware-flow.json'
} else {
    $scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
}

if (-not $SkipPowerOff) {
    & (Join-Path $scriptRoot 'Invoke-PowerSplitter.ps1') -Action poweroff -ConfigPath $ConfigPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Chip) {
    & (Join-Path $scriptRoot 'Invoke-Emulator.ps1') -Action program -Chip $Chip -BinFile $BinFile -ConfigPath $ConfigPath
} else {
    & (Join-Path $scriptRoot 'Invoke-Emulator.ps1') -Action program -BinFile $BinFile -ConfigPath $ConfigPath
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipPowerOn) {
    & (Join-Path $scriptRoot 'Invoke-PowerSplitter.ps1') -Action poweron -ConfigPath $ConfigPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

exit 0
