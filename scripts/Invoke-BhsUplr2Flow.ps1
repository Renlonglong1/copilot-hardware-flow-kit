param(
    [string]$ConfigPath,
    [switch]$SkipPowerOff,
    [switch]$SkipPowerOn
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $scriptRoot '..\config\hardware-flow.dbgsh05.json'
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$chip = $config.remote.emulator.defaultChip
$binFile = $config.flow.defaultBinFile

$args = @(
    '-ConfigPath', $ConfigPath,
    '-Chip', $chip,
    '-BinFile', $binFile
)
if ($SkipPowerOff) { $args += '-SkipPowerOff' }
if ($SkipPowerOn) { $args += '-SkipPowerOn' }

& (Join-Path $scriptRoot 'Invoke-HardwareFlow.ps1') @args
exit $LASTEXITCODE

