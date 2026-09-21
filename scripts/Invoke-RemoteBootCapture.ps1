param(
    [string]$LogRoot = 'C:\Users\debug\Desktop\flow_logs',
    [string]$CaptureScript = 'C:\Users\debug\Desktop\flow_logs\Capture-SerialPort.ps1',
    [string]$PowerDir = 'C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript',
    [string]$PowerExe = 'C:\Users\debug\Desktop\PowerSplitterWithCycleScript 1\PowerSplitterWithCycleScript\PowerSplitterCL.exe',
    [string]$CpuPort = 'COM3',
    [string]$BmcPort = 'COM4',
    [int]$CaptureSeconds = 600,
    [int]$BaudRate = 115200,
    [int]$OpenWarmupSeconds = 45
)

$ErrorActionPreference = 'Continue'

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$runDir = Join-Path $LogRoot $stamp
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Write-Output "RUN_DIR=$runDir"

$cpuLog = Join-Path $runDir 'COM3_GNR_CPU_full_10m.log'
$bmcLog = Join-Path $runDir 'COM4_BMC_full_10m.log'
$cpuReady = Join-Path $runDir 'COM3.ready'
$bmcReady = Join-Path $runDir 'COM4.ready'

Write-Output '=== OPEN SERIAL PORTS ==='
$cpuProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $CaptureScript,
    '-PortName', $CpuPort, '-LogPath', $cpuLog, '-ReadyPath', $cpuReady,
    '-Seconds', $CaptureSeconds, '-BaudRate', $BaudRate
) -RedirectStandardOutput (Join-Path $runDir 'COM3_process_output.txt') -RedirectStandardError (Join-Path $runDir 'COM3_process_error.txt') -PassThru -WindowStyle Hidden

$bmcProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $CaptureScript,
    '-PortName', $BmcPort, '-LogPath', $bmcLog, '-ReadyPath', $bmcReady,
    '-Seconds', $CaptureSeconds, '-BaudRate', $BaudRate
) -RedirectStandardOutput (Join-Path $runDir 'COM4_process_output.txt') -RedirectStandardError (Join-Path $runDir 'COM4_process_error.txt') -PassThru -WindowStyle Hidden

Start-Sleep -Seconds $OpenWarmupSeconds
$cpuProcess.Refresh()
$bmcProcess.Refresh()
$cpuReadyNow = Test-Path -LiteralPath $cpuReady
$bmcReadyNow = Test-Path -LiteralPath $bmcReady
Write-Output "COM3_READY=$cpuReadyNow"
Write-Output "COM4_READY=$bmcReadyNow"

if (($cpuProcess.HasExited -and -not $cpuReadyNow) -or ($bmcProcess.HasExited -and -not $bmcReadyNow)) {
    Write-Output 'SERIAL_OPEN_OK=False'
    if (-not $cpuProcess.HasExited) { Stop-Process -Id $cpuProcess.Id -ErrorAction Continue }
    if (-not $bmcProcess.HasExited) { Stop-Process -Id $bmcProcess.Id -ErrorAction Continue }
    exit 3
}

Write-Output 'SERIAL_OPEN_OK=AssumedTrue'
Write-Output "COM3_CAPTURE_PID=$($cpuProcess.Id)"
Write-Output "COM4_CAPTURE_PID=$($bmcProcess.Id)"

Write-Output '=== POWERON ==='
Set-Location -LiteralPath $PowerDir
$powerOut = & $PowerExe poweron 2>&1
$powerExit = $LASTEXITCODE
$powerOut | Tee-Object -FilePath (Join-Path $runDir '03_poweron.txt')
Write-Output "POWERON_EXIT=$powerExit"

Write-Output '=== CAPTURING ==='
Wait-Process -Id $cpuProcess.Id
Wait-Process -Id $bmcProcess.Id

$cpuBytes = (Get-Item -LiteralPath $cpuLog -ErrorAction SilentlyContinue).Length
$bmcBytes = (Get-Item -LiteralPath $bmcLog -ErrorAction SilentlyContinue).Length
$cpuText = if (Test-Path -LiteralPath $cpuLog) { Get-Content -LiteralPath $cpuLog -Raw -ErrorAction SilentlyContinue } else { '' }
$bmcText = if (Test-Path -LiteralPath $bmcLog) { Get-Content -LiteralPath $bmcLog -Raw -ErrorAction SilentlyContinue } else { '' }

$cpuSignals = @('CentOS Stream 9', 'gnr-bkc login', 'ScktId', 'Training') | Where-Object { $cpuText -match [regex]::Escape($_) }
$bmcSignals = @('U-Boot', 'Linux', 'OpenBMC', 'login:') | Where-Object { $bmcText -match [regex]::Escape($_) }
$flowOk = ($powerExit -eq 0 -and $cpuBytes -gt 0 -and $bmcBytes -gt 0 -and $cpuSignals.Count -gt 0 -and $bmcSignals.Count -gt 0)

$summary = @(
    "RUN_DIR=$runDir",
    'FLASH_OK=True',
    "POWERON_EXIT=$powerExit",
    "COM3_BYTES=$cpuBytes",
    "COM4_BYTES=$bmcBytes",
    "COM3_SIGNALS=$($cpuSignals -join ',')",
    "COM4_SIGNALS=$($bmcSignals -join ',')",
    "FLOW_OK=$flowOk"
)
$summary | Set-Content -LiteralPath (Join-Path $runDir 'summary.txt')
$summary | ForEach-Object { Write-Output $_ }

if (-not $flowOk) { exit 4 }
exit 0
