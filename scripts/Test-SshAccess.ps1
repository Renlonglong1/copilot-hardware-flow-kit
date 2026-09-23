param(
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$target = "$($config.ssh.user)@$($config.ssh.host)"
$sshArguments = Get-HardwareSshArguments -Config $config

Write-Host "Testing SSH access to $target ..."
ssh @sshArguments $target "echo SSH_OK"
exit $LASTEXITCODE
