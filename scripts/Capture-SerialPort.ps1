param(
    [Parameter(Mandatory = $true)]
    [string]$PortName,

    [Parameter(Mandatory = $true)]
    [string]$LogPath,

    [Parameter(Mandatory = $true)]
    [string]$ReadyPath,

    [int]$Seconds = 600,
    [int]$BaudRate = 115200
)

$ErrorActionPreference = 'Stop'

$serial = New-Object System.IO.Ports.SerialPort $PortName, $BaudRate, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 500
$serial.WriteTimeout = 500
$serial.Open()
Set-Content -LiteralPath $ReadyPath -Value 'OPEN'

$writer = New-Object System.IO.StreamWriter($LogPath, $false, [System.Text.Encoding]::ASCII)
$deadline = (Get-Date).AddSeconds($Seconds)
try {
    while ((Get-Date) -lt $deadline) {
        $data = $serial.ReadExisting()
        if ($data.Length -gt 0) {
            $writer.Write($data)
            $writer.Flush()
        } else {
            Start-Sleep -Milliseconds 100
        }
    }
}
finally {
    $writer.Flush()
    $writer.Close()
    $serial.Close()
}
