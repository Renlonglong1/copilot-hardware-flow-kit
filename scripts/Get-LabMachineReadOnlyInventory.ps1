<#
.SYNOPSIS
Performs a noninteractive, read-only inventory of an approved Windows lab-control server.

.DESCRIPTION
This script deliberately requires the local private-identity and dedicated known_hosts
paths as arguments.  Neither is stored in the repository.  It never opens a serial
port or invokes hardware-control tools; it only reads filesystem/PnP metadata.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$HostName,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$UserName,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$IdentityFile,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$KnownHostsFile,

    [ValidateRange(1, 60)]
    [int]$ConnectTimeoutSeconds = 10,

    [string[]]$AdditionalPath = @()
)

$ErrorActionPreference = 'Stop'

# Do not add tool "--help" calls here: some vendor wrappers initialize loggers before
# argument parsing. File-version metadata is sufficient for a strictly read-only probe.
$paths = @(
    'C:\Program Files (x86)\DediProg\Emulator\smucmd.exe',
    'C:\Program Files (x86)\DediProg\EM100\help.pdf',
    'C:\tools\PowerSplitter\PowerSplitterCL.exe',
    'C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe',
    'C:\Users\debug\Desktop\BKC',
    'C:\Users\debug\Desktop\CScripts'
) + $AdditionalPath

$escapedPaths = $paths | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }
$remoteScript = @"
`$ErrorActionPreference = 'Continue'
`$paths = @($($escapedPaths -join ', '))
[pscustomobject]@{
  ComputerName = `$env:COMPUTERNAME
  OsCaption = (Get-CimInstance Win32_OperatingSystem).Caption
  Paths = foreach (`$path in `$paths) {
    if (Test-Path -LiteralPath `$path) {
      `$item = Get-Item -LiteralPath `$path
      [pscustomobject]@{
        Path = `$item.FullName
        Type = if (`$item.PSIsContainer) { 'directory' } else { 'file' }
        Length = if (`$item.PSIsContainer) { `$null } else { `$item.Length }
        FileVersion = if (`$item.PSIsContainer) { `$null } else { `$item.VersionInfo.FileVersion }
      }
    } else {
      [pscustomobject]@{ Path = `$path; Type = 'missing'; Length = `$null; FileVersion = `$null }
    }
  }
  RelevantPnP = Get-CimInstance Win32_PnPEntity |
    Where-Object { `$_.Name -match 'DediProg|EM100|PowerSplitter|COM[0-9]+|FTDI|CP210' } |
    Select-Object Name, Status, PNPDeviceID
}
"@

$encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))
$sshArguments = @(
    '-o', 'BatchMode=yes',
    '-o', "ConnectTimeout=$ConnectTimeoutSeconds",
    '-o', 'ConnectionAttempts=1',
    '-o', 'IdentitiesOnly=yes',
    '-o', 'PasswordAuthentication=no',
    '-o', 'KbdInteractiveAuthentication=no',
    '-o', 'PreferredAuthentications=publickey',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', "UserKnownHostsFile=$KnownHostsFile",
    '-o', 'GlobalKnownHostsFile=NUL',
    '-i', $IdentityFile,
    "$UserName@$HostName",
    'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
    '-NoProfile',
    '-NonInteractive',
    '-EncodedCommand', $encodedCommand
)

Write-Host "Read-only inventory: $UserName@$HostName"
& ssh @sshArguments
exit $LASTEXITCODE
