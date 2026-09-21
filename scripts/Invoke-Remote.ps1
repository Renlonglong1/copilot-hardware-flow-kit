param(
    [Parameter(Mandatory = $true)]
    [string]$Command,

    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$target = "$($config.ssh.user)@$($config.ssh.host)"
$sshArguments = Get-HardwareSshArguments -Config $config

ssh @sshArguments $target $Command
exit $LASTEXITCODE
