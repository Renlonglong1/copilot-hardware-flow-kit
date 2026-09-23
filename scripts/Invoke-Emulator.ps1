param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('help', 'stop', 'start', 'program', 'read', 'blank', 'sum', 'file-sum')]
    [string]$Action,

    [string]$Chip,
    [string]$BinFile,
    [string]$OutputFile,
    [string]$Address,
    [string]$Length,
    [int]$Device = 0,
    [string]$DeviceSerialNumber,

    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$target = "$($config.ssh.user)@$($config.ssh.host)"
$sshArguments = Get-HardwareSshArguments -Config $config
$exe = $config.remote.emulator.exe
$dir = $config.remote.emulator.dir
if (-not $Chip) {
    $Chip = $config.remote.emulator.defaultChip
    if ([string]::IsNullOrWhiteSpace($Chip)) {
        throw 'Chip is required for program. Supply -Chip or configure remote.emulator.defaultChip.'
    }
    Write-Output "EMULATOR_CHIP_CONFIG_DEFAULT=$Chip"
}

$parts = @()
switch ($Action) {
    'help' { $parts += '-h' }
    'stop' { $parts += '--stop' }
    'start' { $parts += '--start' }
    'program' {
        if (-not $Chip) { throw 'Chip is required for program.' }
        if (-not $BinFile) { throw 'BinFile is required for program.' }
        $parts += '--stop'
        $parts += '--set'
        $parts += $Chip
        $parts += '-d'
        $parts += $BinFile
        if ($config.flow.verifyDownload) { $parts += '-v' }
        $parts += '--start'
    }
    'read' {
        if (-not $Chip) { throw 'Chip is required for read.' }
        if (-not $OutputFile) { throw 'OutputFile is required for read.' }
        $parts += '--set'
        $parts += $Chip
        $parts += '-r'
        $parts += $OutputFile
    }
    'blank' {
        if (-not $Chip) { throw 'Chip is required for blank.' }
        $parts += '--set'
        $parts += $Chip
        $parts += '-b'
    }
    'sum' {
        if (-not $Chip) { throw 'Chip is required for sum.' }
        $parts += '--set'
        $parts += $Chip
        $parts += '-s'
    }
    'file-sum' {
        if (-not $BinFile) { throw 'BinFile is required for file-sum.' }
        $parts += '-f'
        $parts += $BinFile
    }
}

if ($Address) {
    $parts += '-a'
    $parts += $Address
}
if ($Length) {
    $parts += '-l'
    $parts += $Length
}
if ($Device -gt 0) {
    $parts += '--device'
    $parts += $Device
}
if ($DeviceSerialNumber) {
    $parts += '--device-SN'
    $parts += $DeviceSerialNumber
}

$escapedArgs = ($parts | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '
$remoteScript = @"
`$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath '$dir' -PathType Container)) {
    throw "Emulator directory does not exist: $dir"
}
if (-not (Test-Path -LiteralPath '$exe' -PathType Leaf)) {
    throw "Emulator executable does not exist: $exe"
}
Set-Location -LiteralPath '$dir'
& '$exe' $escapedArgs
`$exitCode = `$LASTEXITCODE
if (`$exitCode -ne 0) { exit `$exitCode }
exit 0
"@
$encodedRemoteScript = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))
$remote = "powershell -NoProfile -EncodedCommand $encodedRemoteScript"
Write-Host "Running on ${target}: $exe $($parts -join ' ')"
$output = ssh @sshArguments $target $remote 2>&1
$sshExitCode = $LASTEXITCODE
$output | ForEach-Object { Write-Output $_ }
if ($sshExitCode -ne 0) {
    exit $sshExitCode
}
if (($output -join "`n") -match 'No device is connected|Can not find connected|Cannot find connected|failed|error') {
    exit 2
}
exit 0
