param(
    [Parameter(Mandatory = $true)]
    [string]$Command,

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

ssh -o BatchMode=yes -o ConnectTimeout=$timeout $target $Command
exit $LASTEXITCODE
