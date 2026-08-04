param(
    [Parameter(Mandatory = $true)]
    [string]$InputJson,

    [string]$TemplatePath,

    [string]$OutputDirectory,

    [switch]$DeleteInputJson
)

$ErrorActionPreference = 'Stop'

$resolvedScriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($resolvedScriptRoot) -and $MyInvocation.MyCommand.Path) {
    $resolvedScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($resolvedScriptRoot)) {
    $resolvedScriptRoot = Get-Location
}

$skillRoot = Split-Path -Parent $resolvedScriptRoot
if ([string]::IsNullOrWhiteSpace($TemplatePath)) {
    $TemplatePath = Join-Path $skillRoot 'HSD_Sample.xlsx'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $skillRoot 'generated'
}

function Get-RequiredValue {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Data,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = $Data.$Name
    if ([string]::IsNullOrWhiteSpace([string]$value)) {
        throw "Missing required field '$Name' in input JSON."
    }

    return [string]$value
}

function Get-OptionalValue {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Data,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = $Data.$Name
    if ($null -eq $value) {
        return ''
    }

    return [string]$value
}

function ConvertTo-NormalizedConclusion {
    param(
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ''
    }

    $normalized = $Value.Trim()
    $canonicalValues = @(
        'Cannot import',
        'Natural import',
        'Suggested import',
        'Need import'
    )

    foreach ($canonicalValue in $canonicalValues) {
        if ($normalized -ieq $canonicalValue -or $normalized -imatch ('^{0}(\s*:.*)?$' -f [regex]::Escape($canonicalValue))) {
            return $canonicalValue
        }
    }

    throw "Conclusion must be one of: Cannot import, Natural import, Suggested import, Need import. Received: $Value"
}

function Join-DetailsText {
    param(
        [string]$Severity,
        [string]$Owner,
        [string]$Component,
        [string]$Status,
        [string]$SubmittedDate,
        [string]$Comments
    )

    $parts = @()
    if (-not [string]::IsNullOrWhiteSpace($Severity)) {
        $parts += "Severity: $Severity"
    }
    if (-not [string]::IsNullOrWhiteSpace($Owner)) {
        $parts += "Owner: $Owner"
    }
    if (-not [string]::IsNullOrWhiteSpace($Component)) {
        $parts += "Component: $Component"
    }
    if (-not [string]::IsNullOrWhiteSpace($Status)) {
        $parts += "Status: $Status"
    }
    if (-not [string]::IsNullOrWhiteSpace($SubmittedDate)) {
        $parts += "Submitted: $SubmittedDate"
    }
    if (-not [string]::IsNullOrWhiteSpace($Comments)) {
        $parts += "Notes: $Comments"
    }

    return ($parts -join '; ')
}

function Get-SourceSightingText {
    param(
        [psobject]$Data
    )

    $explicitValue = Get-OptionalValue -Data $Data -Name 'SourceSighting'
    if (-not [string]::IsNullOrWhiteSpace($explicitValue)) {
        return $explicitValue
    }

    $tenantSubject = Get-OptionalValue -Data $Data -Name 'SourceSightingTenantSubject'
    $sightingId = Get-OptionalValue -Data $Data -Name 'SourceSightingId'
    $sightingUrl = Get-OptionalValue -Data $Data -Name 'SourceSightingUrl'
    $parts = @($tenantSubject, $sightingId, $sightingUrl) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    return ($parts -join ' / ')
}

function Join-RootCauseText {
    param(
        [string]$RootCause,
        [string]$FinalSolution
    )

    $parts = @()
    if (-not [string]::IsNullOrWhiteSpace($RootCause)) {
        $parts += "Root cause: $RootCause"
    }
    if (-not [string]::IsNullOrWhiteSpace($FinalSolution)) {
        $parts += "Fix: $FinalSolution"
    }

    return ($parts -join '; ')
}

function Resolve-IssueDomain {
    param(
        [string]$ExplicitDomain,
        [string]$IssueTitle,
        [string]$ProblemDescription
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitDomain)) {
        return $ExplicitDomain.Trim()
    }

    $text = (@($IssueTitle, $ProblemDescription) -join ' ')
    if ([string]::IsNullOrWhiteSpace($text)) {
        return 'Other'
    }

    if ($text -imatch '(runtime\s*sPPR|\bsPPR\b|runtime\s*ppr)') {
        return 'Runtime sPPR'
    }
    if ($text -imatch '(legacy\s*iio|iio\s*stack|\bIIO\b)') {
        return 'legacy IIO stack'
    }
    if ($text -imatch '(\bIOMMU\b|\bIOMU\b|vt-d|\bvtd\b)') {
        return 'IOMU'
    }
    if ($text -imatch '\bTDX\b|trust\s*domain') {
        return 'TDX'
    }
    if ($text -imatch '(\bDSA\b|data\s*streaming\s*accelerator|\bidxd\b)') {
        return 'DSA'
    }
    if ($text -imatch '(\bMMIO\b|memory\s*-?mapped\s*(i/o|io))') {
        return 'MMIO'
    }

    return 'Other'
}

if (-not (Test-Path -LiteralPath $InputJson)) {
    throw "Input JSON not found: $InputJson"
}

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    throw "Output directory not found: $OutputDirectory"
}

$inputData = Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json

$ticketId = Get-RequiredValue -Data $inputData -Name 'TicketId'
$issueTitle = Get-RequiredValue -Data $inputData -Name 'IssueTitle'
$problemDescription = Get-RequiredValue -Data $inputData -Name 'ProblemDescription'
$domain = Resolve-IssueDomain -ExplicitDomain (Get-OptionalValue -Data $inputData -Name 'Domain') -IssueTitle $issueTitle -ProblemDescription $problemDescription
$systemConfiguration = Get-RequiredValue -Data $inputData -Name 'SystemConfigurationAndReproductionStep'
$rootCause = Get-RequiredValue -Data $inputData -Name 'RootCause'
$finalSolution = Get-OptionalValue -Data $inputData -Name 'FinalSolution'
$affectedProducts = Get-RequiredValue -Data $inputData -Name 'AffectedProducts'
$severity = Get-OptionalValue -Data $inputData -Name 'Severity'
$owner = Get-OptionalValue -Data $inputData -Name 'Owner'
$component = Get-OptionalValue -Data $inputData -Name 'Component'
$status = Get-OptionalValue -Data $inputData -Name 'Status'
$submittedDate = Get-OptionalValue -Data $inputData -Name 'SubmittedDate'
$comments = Get-OptionalValue -Data $inputData -Name 'Comments'
$conclusion = ConvertTo-NormalizedConclusion -Value (Get-OptionalValue -Data $inputData -Name 'Conclusion')
$details = Join-DetailsText -Severity $severity -Owner $owner -Component $component -Status $status -SubmittedDate $submittedDate -Comments $comments
$sourceSighting = Get-SourceSightingText -Data $inputData
$rootCauseText = Join-RootCauseText -RootCause $rootCause -FinalSolution $finalSolution

$dateString = [string]$inputData.Date
if ([string]::IsNullOrWhiteSpace($dateString)) {
    $dateString = Get-Date -Format 'yyyyMMdd'
}

if ($dateString -notmatch '^\d{8}$') {
    throw "Date must use YYYYMMDD format. Received: $dateString"
}

$outputPath = Join-Path $OutputDirectory ("HSD_{0}_analysis_{1}.xlsx" -f $ticketId, $dateString)
if (Test-Path -LiteralPath $outputPath) {
    try {
        Remove-Item -LiteralPath $outputPath -Force
    }
    catch {
        throw "Output file is locked or in use: $outputPath. Close the workbook or choose a different YYYYMMDD date."
    }
}

$excel = $null
$sourceWorkbook = $null
$sourceWorksheet = $null
$destinationWorkbook = $null
$destinationWorksheet = $null
$result = $null
$templateAvailable = Test-Path -LiteralPath $TemplatePath

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $destinationWorkbook = $excel.Workbooks.Add()
    $destinationWorksheet = $destinationWorkbook.Worksheets.Item(1)
    $destinationWorksheet.Name = 'Sheet1'

    if ($templateAvailable) {
        $sourceWorkbook = $excel.Workbooks.Open($TemplatePath)
        $sourceWorksheet = $sourceWorkbook.Worksheets.Item(1)

        $sourceWorksheet.Range('A1:I1').Copy($destinationWorksheet.Range('A1:I1'))

        $destinationWorksheet.Columns.Item(3).Insert()

        foreach ($column in 1..9) {
            $destinationWorksheet.Columns.Item($column).ColumnWidth = $sourceWorksheet.Columns.Item($column).ColumnWidth
        }

        $destinationWorksheet.Columns.Item(10).ColumnWidth = $destinationWorksheet.Columns.Item(9).ColumnWidth

        $destinationWorksheet.Rows.Item(1).RowHeight = $sourceWorksheet.Rows.Item(1).RowHeight

        $destinationWorksheet.Cells.Item(1, 3).Value2 = 'Domain'

        # Keep the inserted column visually consistent with adjacent header cells.
        $destinationWorksheet.Range('B1').Copy()
        $destinationWorksheet.Range('C1').PasteSpecial(-4122)
        $excel.CutCopyMode = $false
    }
    else {
        $headers = @(
            'HSD ID Number',
            'Issue title',
            'Domain',
            'Problem Description',
            'System Configuration & Reproduction Step',
            'Root Cause',
            'Affected Products',
            'Details',
            'Conclusion',
            'Source Sighting'
        )
        $columnWidths = @(18, 48, 22, 64, 64, 64, 28, 48, 36, 44)

        foreach ($index in 0..9) {
            $headerCell = $destinationWorksheet.Cells.Item(1, $index + 1)
            $headerCell.Value2 = $headers[$index]
            $headerCell.Font.Bold = $true
            $headerCell.Interior.Color = 0xD9EAF7
            $headerCell.WrapText = $true
            $destinationWorksheet.Columns.Item($index + 1).ColumnWidth = $columnWidths[$index]
        }

        $destinationWorksheet.Rows.Item(1).RowHeight = 30
    }

    $destinationWorksheet.Cells.Item(1, 1).Value2 = 'HSD ID Number'
    $destinationWorksheet.Cells.Item(1, 3).Value2 = 'Domain'
    $destinationWorksheet.Cells.Item(1, 8).Value2 = 'Details'
    $destinationWorksheet.Cells.Item(1, 9).Value2 = 'Conclusion'
    $destinationWorksheet.Cells.Item(1, 10).Value2 = 'Source Sighting'
    $destinationWorksheet.Cells.Item(2, 1).Formula = "'" + $ticketId
    $destinationWorksheet.Cells.Item(2, 2).Value2 = $issueTitle
    $destinationWorksheet.Cells.Item(2, 3).Value2 = $domain
    $destinationWorksheet.Cells.Item(2, 4).Value2 = $problemDescription
    $destinationWorksheet.Cells.Item(2, 5).Value2 = $systemConfiguration
    $destinationWorksheet.Cells.Item(2, 6).Value2 = $rootCauseText
    $destinationWorksheet.Cells.Item(2, 7).Value2 = $affectedProducts
    $destinationWorksheet.Cells.Item(2, 8).Value2 = $details
    $destinationWorksheet.Cells.Item(2, 9).Value2 = $conclusion
    $destinationWorksheet.Cells.Item(2, 10).Value2 = $sourceSighting
    $destinationWorksheet.Range('A2:J2').WrapText = $true
    $destinationWorksheet.Range('A2:J2').VerticalAlignment = -4160
    $destinationWorksheet.Rows.Item(2).AutoFit() | Out-Null

    $destinationWorkbook.SaveAs($outputPath, 51)

    $result = [pscustomobject]@{
        OutputPath = $outputPath
        TemplateUsed = $(if ($templateAvailable) { $TemplatePath } else { '' })
        TicketId = [string]$destinationWorksheet.Range('A2').Value2
        HeaderA1 = [string]$destinationWorksheet.Range('A1').Text
        HeaderB1 = [string]$destinationWorksheet.Range('B1').Text
        HeaderC1 = [string]$destinationWorksheet.Range('C1').Text
        HeaderH1 = [string]$destinationWorksheet.Range('H1').Text
        HeaderI1 = [string]$destinationWorksheet.Range('I1').Text
        HeaderJ1 = [string]$destinationWorksheet.Range('J1').Text
        IssueTitle = [string]$destinationWorksheet.Range('B2').Value2
        Domain = [string]$destinationWorksheet.Range('C2').Value2
        RootCause = [string]$destinationWorksheet.Range('F2').Value2
        Conclusion = [string]$destinationWorksheet.Range('I2').Value2
        SourceSighting = [string]$destinationWorksheet.Range('J2').Value2
    }

    if ($DeleteInputJson) {
        Remove-Item -LiteralPath $InputJson -Force
    }

    $destinationWorkbook.Close($true)
    $destinationWorksheet = $null
    $destinationWorkbook = $null

    if ($sourceWorkbook) {
        $sourceWorkbook.Close($false)
        $sourceWorksheet = $null
        $sourceWorkbook = $null
    }

    if ($excel) {
        $excel.Quit() | Out-Null
        $excel = $null
    }

    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
finally {
    if ($destinationWorkbook) {
        $destinationWorkbook.Close($true)
    }
    if ($sourceWorkbook) {
        $sourceWorkbook.Close($false)
    }
    if ($excel) {
        $excel.Quit() | Out-Null
    }
}

if ($result) {
    $result | ConvertTo-Json -Compress
}