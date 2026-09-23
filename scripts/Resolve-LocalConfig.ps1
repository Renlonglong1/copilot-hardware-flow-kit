function Resolve-HardwareFlowConfigPath {
    param(
        [string]$ConfigPath,
        [Parameter(Mandatory = $true)]
        [string]$ScriptRoot
    )

    $kitRoot = Split-Path -Parent $ScriptRoot
    $candidates = @(
        $ConfigPath,
        $env:COPILOT_HARDWARE_FLOW_CONFIG,
        (Join-Path $kitRoot 'config\local\hardware-flow.json'),
        (Join-Path $HOME 'copilot-hardware-flow-local\hardware-flow.json')
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw 'Hardware-flow config is required. Supply -ConfigPath, set COPILOT_HARDWARE_FLOW_CONFIG, or create config\local\hardware-flow.json from config\hardware-flow.template.json.'
}

function Get-HardwareSshArguments {
    param([Parameter(Mandatory = $true)]$Config)

    $arguments = @('-o', 'BatchMode=yes', '-o', "ConnectTimeout=$([int]$Config.ssh.connectTimeoutSeconds)")
    if ($Config.ssh.identityFile) {
        $identityFile = [Environment]::ExpandEnvironmentVariables([string]$Config.ssh.identityFile)
        if (-not (Test-Path -LiteralPath $identityFile -PathType Leaf)) {
            throw "Configured SSH identity file does not exist: $identityFile"
        }
        $arguments += @('-o', 'IdentitiesOnly=yes', '-i', $identityFile)
    }
    if ($Config.ssh.hostKeyAlias) {
        $arguments += @('-o', "HostKeyAlias=$($Config.ssh.hostKeyAlias)")
    }
    return $arguments
}
