param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('help', 'poweron', 'poweroff', 'powercycle', 'portpower')]
    [string]$Action,

    [int]$CycleSeconds = 10,
    [int]$Port = 1,
    [bool]$PortEnabled = $true,

    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

if (-not $ConfigPath) {
    $scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $ConfigPath = Join-Path $scriptRoot '..\config\hardware-flow.json'
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$target = "$($config.ssh.user)@$($config.ssh.host)"
$timeout = [int]$config.ssh.connectTimeoutSeconds
$exe = $config.remote.powerSplitter.exe
$dir = $config.remote.powerSplitter.dir

switch ($Action) {
    'help' { $argsText = '/?' }
    'poweron' { $argsText = 'poweron' }
    'poweroff' { $argsText = 'poweroff' }
    'powercycle' { $argsText = "powercycle $CycleSeconds" }
    'portpower' { $argsText = "portpower $Port $($PortEnabled.ToString().ToLowerInvariant())" }
}

$remoteScript = @"
Set-Location -LiteralPath '$dir'
& '$exe' $argsText
exit `$LASTEXITCODE
"@
$encodedRemoteScript = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))
$remote = "powershell -NoProfile -EncodedCommand $encodedRemoteScript"
Write-Host "Running on ${target}: $exe $argsText"
ssh -o BatchMode=yes -o ConnectTimeout=$timeout $target $remote
exit $LASTEXITCODE
