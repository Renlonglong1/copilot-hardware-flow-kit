param(
    [string]$ConfigPath,
    [switch]$SkipPowerOff,
    [switch]$SkipPowerOn
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$binFile = $config.flow.defaultBinFile

$args = @(
    '-ConfigPath', $ConfigPath,
    '-BinFile', $binFile
)
if ($SkipPowerOff) { $args += '-SkipPowerOff' }
if ($SkipPowerOn) { $args += '-SkipPowerOn' }

& (Join-Path $scriptRoot 'Invoke-HardwareFlow.ps1') @args
exit $LASTEXITCODE
