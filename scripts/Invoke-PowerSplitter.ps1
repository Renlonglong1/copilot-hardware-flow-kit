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

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$target = "$($config.ssh.user)@$($config.ssh.host)"
$sshArguments = Get-HardwareSshArguments -Config $config
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
`$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath '$dir' -PathType Container)) {
    throw "PowerSplitter directory does not exist: $dir"
}
if (-not (Test-Path -LiteralPath '$exe' -PathType Leaf)) {
    throw "PowerSplitter executable does not exist: $exe"
}
Set-Location -LiteralPath '$dir'
& '$exe' $argsText
`$exitCode = `$LASTEXITCODE
if (`$exitCode -ne 0) { exit `$exitCode }
exit 0
"@
$encodedRemoteScript = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))
$remote = "powershell -NoProfile -EncodedCommand $encodedRemoteScript"
Write-Host "Running on ${target}: $exe $argsText"
ssh @sshArguments $target $remote
exit $LASTEXITCODE
