param(
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

Write-Host "Testing SSH access to $target ..."
ssh -o BatchMode=yes -o ConnectTimeout=$timeout $target "cd & echo SSH_OK"
exit $LASTEXITCODE
