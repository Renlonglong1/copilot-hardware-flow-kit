param(
    [string]$PortName = 'COM3',
    [int]$BaudRate = 115200,
    [string]$WindowsLogRoot = 'C:\Users\debug\Desktop\flow_logs',
    [string]$MlcDir = '/root/mlc_v3.11b',
    [string]$UserName = 'root',
    [string]$Password = 'dcpae_123',
    [int]$CommandTimeoutSeconds = 1200
)

$ErrorActionPreference = 'Stop'

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$runDir = Join-Path $WindowsLogRoot "mlc_$stamp"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$serialLog = Join-Path $runDir 'COM3_mlc_interaction.log'
$hostResultsPath = Join-Path $runDir 'host_mlc_results.log'
$summaryPath = Join-Path $runDir 'mlc_summary.txt'

function Read-SerialUntil {
    param(
        [System.IO.Ports.SerialPort]$Serial,
        [string[]]$Patterns,
        [int]$TimeoutSeconds,
        [System.IO.StreamWriter]$Writer
    )

    $buffer = ''
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $chunk = $Serial.ReadExisting()
        if ($chunk.Length -gt 0) {
            $buffer += $chunk
            $Writer.Write($chunk)
            $Writer.Flush()
            foreach ($pattern in $Patterns) {
                if ($buffer -match [regex]::Escape($pattern)) {
                    return @{ Found = $true; Pattern = $pattern; Text = $buffer }
                }
            }
        } else {
            Start-Sleep -Milliseconds 200
        }
    }
    return @{ Found = $false; Pattern = ''; Text = $buffer }
}

function Drain-Serial {
    param([System.IO.Ports.SerialPort]$Serial)
    Start-Sleep -Milliseconds 300
    [void]$Serial.ReadExisting()
}

function Send-Line {
    param(
        [System.IO.Ports.SerialPort]$Serial,
        [System.IO.StreamWriter]$Writer,
        [string]$Line,
        [switch]$RedactInLog
    )
    $loggedLine = if ($RedactInLog) { '[REDACTED]' } else { $Line }
    $Writer.WriteLine("`n>>> $loggedLine")
    $Writer.Flush()
    $Serial.Write("$Line`r")
}

function Invoke-HostCommand {
    param(
        [System.IO.Ports.SerialPort]$Serial,
        [System.IO.StreamWriter]$Writer,
        [string]$Command,
        [int]$TimeoutSeconds
    )

    Drain-Serial $Serial
    $start = Get-Date
    Send-Line $Serial $Writer $Command
    $result = Read-SerialUntil $Serial @('[root@gnr-bkc mlc_v3.11b]#', '[root@gnr-bkc ~]#') $TimeoutSeconds $Writer
    $duration = [int]((Get-Date) - $start).TotalSeconds
    if (-not $result.Found) {
        throw "HOST_COMMAND_TIMEOUT after ${duration}s: $Command"
    }
    return @{
        Duration = $duration
        Text = $result.Text
    }
}

Write-Output "MLC_RUN_DIR=$runDir"

$serial = New-Object System.IO.Ports.SerialPort $PortName, $BaudRate, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 500
$serial.WriteTimeout = 500
$serial.Open()
$writer = New-Object System.IO.StreamWriter($serialLog, $false, [System.Text.Encoding]::ASCII)

try {
    Send-Line $serial $writer ''
    $loginProbe = Read-SerialUntil $serial @('gnr-bkc login:', 'login:', '[root@gnr-bkc mlc_v3.11b]#', '[root@gnr-bkc ~]#') 90 $writer
    if ($loginProbe.Pattern -match 'login:') {
        Send-Line $serial $writer $UserName
        $passwordProbe = Read-SerialUntil $serial @('Password:') 30 $writer
        if (-not $passwordProbe.Found) { throw 'PASSWORD_PROMPT_NOT_FOUND' }
        Send-Line $serial $writer $Password -RedactInLog
        $shellProbe = Read-SerialUntil $serial @('[root@gnr-bkc mlc_v3.11b]#', '[root@gnr-bkc ~]#') 90 $writer
        if (-not $shellProbe.Found) { throw 'ROOT_SHELL_NOT_FOUND_AFTER_LOGIN' }
    } elseif (-not $loginProbe.Found) {
        throw 'LOGIN_OR_ROOT_SHELL_PROMPT_NOT_FOUND'
    }

    $hostResultDir = "$MlcDir/copilot_mlc_results_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    $commands = @(
        @{ Name = '00_env'; Command = "cd $MlcDir && mkdir -p $hostResultDir && { whoami; uname -a; ./mlc --help | head -40; } > $hostResultDir/00_env.log 2>&1" },
        @{ Name = '01_idle_latency'; Command = "cd $MlcDir && { ./mlc --idle_latency; echo EXIT:`$?; } > $hostResultDir/01_idle_latency.log 2>&1" },
        @{ Name = '02_latency_matrix'; Command = "cd $MlcDir && { ./mlc --latency_matrix; echo EXIT:`$?; } > $hostResultDir/02_latency_matrix.log 2>&1" },
        @{ Name = '03_bandwidth_matrix'; Command = "cd $MlcDir && { ./mlc --bandwidth_matrix; echo EXIT:`$?; } > $hostResultDir/03_bandwidth_matrix.log 2>&1" },
        @{ Name = '04_peak_injection_bandwidth'; Command = "cd $MlcDir && { ./mlc --peak_injection_bandwidth; echo EXIT:`$?; } > $hostResultDir/04_peak_injection_bandwidth.log 2>&1" },
        @{ Name = '05_loaded_latency'; Command = "cd $MlcDir && { ./mlc --loaded_latency; echo EXIT:`$?; } > $hostResultDir/05_loaded_latency.log 2>&1" },
        @{ Name = '06_c2c_latency'; Command = "cd $MlcDir && { ./mlc --c2c_latency; echo EXIT:`$?; } > $hostResultDir/06_c2c_latency.log 2>&1" }
    )

    $results = New-Object System.Collections.Generic.List[string]
    [void](Invoke-HostCommand $serial $writer 'modprobe msr || true' 90)
    foreach ($item in $commands) {
        $commandResult = Invoke-HostCommand $serial $writer $item.Command $CommandTimeoutSeconds
        $results.Add("$($item.Name): DONE duration=$($commandResult.Duration)s")
    }

    $checkCommand = "cd $MlcDir && ls -l $hostResultDir && grep --color=never -H 'EXIT:' $hostResultDir/*.log"
    $checkResult = Invoke-HostCommand $serial $writer $checkCommand 180

    $captureCommand = "cd $MlcDir && for result in $hostResultDir/*.log; do printf '\n===FILE:%s===\n' `"`$(basename `"`$result`")`"; cat `"`$result`"; done; printf '\n__COPILOT_MLC_RESULTS_END__\n'"
    $captureResult = Invoke-HostCommand $serial $writer $captureCommand 180
    if ($captureResult.Text -notmatch '__COPILOT_MLC_RESULTS_END__') {
        throw 'MLC_HOST_RESULTS_CAPTURE_INCOMPLETE'
    }
    $captureResult.Text | Set-Content -LiteralPath $hostResultsPath -Encoding ASCII

    $writer.Flush()
    $checkText = $checkResult.Text -replace "`e\[[0-?]*[ -/]*[@-~]", ''
    $exitMatches = [regex]::Matches($checkText, '(?m)^[^\s]+/[0-9][^:\s]+\.log:EXIT:(\d+)\s*$')
    $nonZero = @()
    foreach ($match in $exitMatches) {
        if ($match.Groups[1].Value -ne '0') { $nonZero += $match.Value }
    }
    $mlcOk = ($exitMatches.Count -ge 6 -and $nonZero.Count -eq 0)

    $summary = @(
        "MLC_SERIAL_LOG=$serialLog",
        "MLC_HOST_RESULT_DIR=$hostResultDir",
        "MLC_HOST_RESULTS_CAPTURE=$hostResultsPath",
        "MLC_EXIT_LINE_COUNT=$($exitMatches.Count)",
        "MLC_NONZERO_EXIT=$($nonZero -join ',')",
        "MLC_OK=$mlcOk"
    ) + $results
    $summary | Set-Content -LiteralPath $summaryPath
    $summary | ForEach-Object { Write-Output $_ }

    if (-not $mlcOk) { exit 5 }
    exit 0
}
finally {
    $writer.Flush()
    $writer.Close()
    $serial.Close()
}
