param(
    [string]$ConfigPath,
    [Alias('Host')]
    [string]$BindHost,
    [int]$Port,
    [switch]$SubprocessMode,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$kitRoot = Split-Path -Parent $scriptRoot

if (-not $ConfigPath) {
    $localConfig = Join-Path $kitRoot 'config\local\ips-copilot-ui.json'
    $ConfigPath = if (Test-Path -LiteralPath $localConfig -PathType Leaf) {
        $localConfig
    } else {
        Join-Path $kitRoot 'config\ips-copilot-ui.template.json'
    }
}

$argsList = @(
    (Join-Path $scriptRoot 'ips_copilot_ui.py'),
    '--config',
    $ConfigPath
)

if ($SubprocessMode) {
    $argsList += '--copilot-mode'
    $argsList += 'subprocess'
}

if ($BindHost) {
    $argsList += '--host'
    $argsList += $BindHost
}

if ($Port) {
    $argsList += '--port'
    $argsList += $Port
}

if ($NoBrowser) {
    $argsList += '--no-browser'
}

py @argsList
exit $LASTEXITCODE
