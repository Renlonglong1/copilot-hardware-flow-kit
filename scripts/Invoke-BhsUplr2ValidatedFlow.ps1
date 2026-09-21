param(
    [string]$ConfigPath,
    [switch]$RunMlc,
    [switch]$CloseGuiConflicts
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
. (Join-Path $scriptRoot 'Resolve-LocalConfig.ps1')
$ConfigPath = Resolve-HardwareFlowConfigPath -ConfigPath $ConfigPath -ScriptRoot $scriptRoot

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$target = "$($config.ssh.user)@$($config.ssh.host)"
$sshArguments = Get-HardwareSshArguments -Config $config
$bin = $config.flow.defaultBinFile
$logRoot = $config.flow.logRoot
$remoteCaptureScript = "$logRoot\Invoke-RemoteBootCapture.ps1"
$remotePortScript = "$logRoot\Capture-SerialPort.ps1"
$remoteMlcScript = "$logRoot\Invoke-RemoteMlcSerial.ps1"

function Invoke-RemoteScriptText {
    param([string]$ScriptText)
    $ScriptText | ssh @sshArguments $target "powershell -NoProfile -ExecutionPolicy Bypass -Command -"
    return $LASTEXITCODE
}

function Copy-RemoteFile {
    param([string]$LocalPath, [string]$RemotePath)
    scp @sshArguments $LocalPath "${target}:$($RemotePath -replace '\\','/')"
    if ($LASTEXITCODE -ne 0) { throw "scp failed: $LocalPath -> $RemotePath" }
}

Write-Output "TARGET=$target"
Write-Output "CONFIG=$ConfigPath"

Write-Output '=== SSH PRECHECK ==='
& (Join-Path $scriptRoot 'Test-SshAccess.ps1') -ConfigPath $ConfigPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$precheck = @"
`$smu = '$($config.remote.emulator.exe)'
`$bin = '$bin'
Write-Output '=== BIN ==='
Get-Item -LiteralPath `$bin | Select-Object FullName,Length,LastWriteTime | Format-List
Get-FileHash -LiteralPath `$bin -Algorithm SHA256 | Format-List
Write-Output '=== GUI/DEDIPROG PROCESSES ==='
Get-CimInstance Win32_Process | Where-Object { `$_.Name -match 'EM100|Emulator|smucmd|DediProg' -or `$_.CommandLine -match 'EM100|Emulator|smucmd|DediProg' } | Select-Object ProcessId,Name,CommandLine | Format-Table -AutoSize -Wrap
Write-Output '=== USB ==='
Get-CimInstance Win32_PnPEntity | Where-Object { `$_.Name -match 'DediProg|EM100' -or `$_.DeviceID -match 'VID_04B4|VID_04D8' } | Select-Object Name,Status,DeviceID | Format-Table -AutoSize -Wrap
Write-Output '=== SMUCMD CHECK ==='
Set-Location -LiteralPath '$($config.remote.emulator.dir)'
& `$smu -c
Write-Output "SMUCMD_CHECK_EXIT=`$LASTEXITCODE"
"@
[void](Invoke-RemoteScriptText $precheck)

if ($CloseGuiConflicts) {
    Write-Output '=== CLOSE GUI CONFLICTS ==='
    $closeScript = @"
Get-CimInstance Win32_Process | Where-Object { `$_.Name -match '^(EM100|Emulator)\.exe$' } | ForEach-Object {
    Write-Output "Stopping `$(`$_.Name) PID=`$(`$_.ProcessId)"
    Stop-Process -Id `$_.ProcessId -ErrorAction Continue
}
Start-Sleep -Seconds 2
Set-Location -LiteralPath '$($config.remote.emulator.dir)'
& '$($config.remote.emulator.exe)' -c
Write-Output "SMUCMD_RECHECK_EXIT=`$LASTEXITCODE"
"@
    [void](Invoke-RemoteScriptText $closeScript)
}

Write-Output '=== POWEROFF ==='
& (Join-Path $scriptRoot 'Invoke-PowerSplitter.ps1') -Action poweroff -ConfigPath $ConfigPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output '=== FLASH ==='
$flashLog = Join-Path $env:TEMP "bhs_uplr2_flash_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
& (Join-Path $scriptRoot 'Invoke-Emulator.ps1') -Action program -BinFile $bin -ConfigPath $ConfigPath 2>&1 | Tee-Object -FilePath $flashLog
$flashExit = $LASTEXITCODE
$flashText = Get-Content -LiteralPath $flashLog -Raw
$required = @('Download Complete', 'Verify Pass', 'Emulator is in Emulation mode', 'Authentication Pass')
$missing = @($required | Where-Object { $flashText -notmatch [regex]::Escape($_) })
$failures = @('No device is connected!', 'Verify Fail', 'Authentication Fail', 'Download failed', 'ERROR')
$hits = @($failures | Where-Object { $flashText -match [regex]::Escape($_) })
$flashOk = ($flashExit -eq 0 -and $missing.Count -eq 0 -and $hits.Count -eq 0)
Write-Output "FLASH_WRAPPER_EXIT=$flashExit"
Write-Output "FLASH_OK=$flashOk"
Write-Output "FLASH_MISSING=$($missing -join ',')"
Write-Output "FLASH_FAILURE_HITS=$($hits -join ',')"
if (-not $flashOk) { exit 2 }

Write-Output '=== DEPLOY BOOT CAPTURE HELPERS ==='
Copy-RemoteFile (Join-Path $scriptRoot 'Capture-SerialPort.ps1') $remotePortScript
Copy-RemoteFile (Join-Path $scriptRoot 'Invoke-RemoteBootCapture.ps1') $remoteCaptureScript

Write-Output '=== BOOT CAPTURE ==='
$bootCaptureCommand = @"
& '$remoteCaptureScript' -LogRoot '$logRoot' -CaptureScript '$remotePortScript' -PowerDir '$($config.remote.powerSplitter.dir)' -PowerExe '$($config.remote.powerSplitter.exe)' -CpuPort '$($config.remote.serial.ports.cpu)' -BmcPort '$($config.remote.serial.ports.bmc)' -CaptureSeconds $($config.flow.captureSeconds) -BaudRate $($config.remote.serial.baudRate)
exit `$LASTEXITCODE
"@
$bootCaptureEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootCaptureCommand))
ssh @sshArguments $target "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $bootCaptureEncoded"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($RunMlc) {
    Write-Output '=== DEPLOY MLC SERIAL HELPER ==='
    Copy-RemoteFile (Join-Path $scriptRoot 'Invoke-RemoteMlcSerial.ps1') $remoteMlcScript
    $mlcDir = '/root/mlc_v3.11b'
    if ($config.hostOs -and $config.hostOs.mlcDir) { $mlcDir = $config.hostOs.mlcDir }
    $mlcCommand = @"
& '$remoteMlcScript' -PortName '$($config.remote.serial.ports.cpu)' -BaudRate $($config.remote.serial.baudRate) -WindowsLogRoot '$logRoot' -MlcDir '$mlcDir'
exit `$LASTEXITCODE
"@
    $mlcEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($mlcCommand))
    ssh @sshArguments $target "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $mlcEncoded"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Output 'VALIDATED_FLOW_OK=True'
exit 0
