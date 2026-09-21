param(
    [string]$Chip,

    [Parameter(Mandatory = $true)]
    [string]$BinFile,

    [switch]$SkipPowerOff,
    [switch]$SkipPowerOn,

    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

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
