param(
    [Parameter(Mandatory=$true)]
    [string]$TicketNumber
)

$hsdUrl = "https://hsdes.intel.com/appstore/article-one/#/$TicketNumber"
Start-Process $hsdUrl
Write-Host "Opening HSD ticket $TicketNumber..."
