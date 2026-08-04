param(
    [Parameter(Mandatory = $true)]
    [string]$InputJson,

    [string]$OutputDirectory,

    [string]$TemplatePath,

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
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $skillRoot 'generated'
}
if ([string]::IsNullOrWhiteSpace($TemplatePath)) {
    $TemplatePath = Join-Path $skillRoot 'HSD_Sample.xlsx'
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

function Normalize-Conclusion {
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

function Get-OptionalList {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Data,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = $Data.$Name
    if ($null -eq $value) {
        return @()
    }

    if ($value -is [System.Array]) {
        return @($value | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }

    if ([string]::IsNullOrWhiteSpace([string]$value)) {
        return @()
    }

    return @([string]$value)
}

function Join-NonEmpty {
    param(
        [string[]]$Values,
        [string]$Separator = '; '
    )

    return (@($Values | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join $Separator)
}

function Format-SourceSighting {
    param(
        [string]$TenantSubject,
        [string]$SightingId,
        [string]$SightingUrl
    )

    $sourceSighting = Join-NonEmpty -Values @($TenantSubject, $SightingId) -Separator ' / '
    if (-not [string]::IsNullOrWhiteSpace($SightingUrl)) {
        $sourceSighting = Join-NonEmpty -Values @($sourceSighting, $SightingUrl) -Separator ' / '
    }

    return $sourceSighting
}

function New-MarkdownDocument {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Data
    )

    $ticketId = Get-RequiredValue -Data $Data -Name 'TicketId'
    $tenantSubject = Get-RequiredValue -Data $Data -Name 'TenantSubject'
    $ticketUrl = Get-OptionalValue -Data $Data -Name 'TicketUrl'
    $issueDescription = Get-RequiredValue -Data $Data -Name 'ProblemDescription'
    $failureSignature = Get-OptionalValue -Data $Data -Name 'FailureSignature'
    $reproduction = Get-RequiredValue -Data $Data -Name 'SystemConfigurationAndReproductionStep'
    $finalSolution = Get-OptionalValue -Data $Data -Name 'FinalSolution'
    $conclusion = Normalize-Conclusion -Value (Get-OptionalValue -Data $Data -Name 'Conclusion')
    $rootCause = Get-RequiredValue -Data $Data -Name 'RootCause'
    $affectedProducts = Get-RequiredValue -Data $Data -Name 'AffectedProducts'
    $release = Get-OptionalValue -Data $Data -Name 'Release'
    $owner = Get-OptionalValue -Data $Data -Name 'Owner'
    $status = Get-OptionalValue -Data $Data -Name 'Status'
    $reason = Get-OptionalValue -Data $Data -Name 'Reason'
    $submittedDate = Get-OptionalValue -Data $Data -Name 'SubmittedDate'
    $component = Get-OptionalValue -Data $Data -Name 'Component'
    $parentId = Get-OptionalValue -Data $Data -Name 'ParentId'
    $sourceSightingTenantSubject = Get-OptionalValue -Data $Data -Name 'SourceSightingTenantSubject'
    $sourceSightingId = Get-OptionalValue -Data $Data -Name 'SourceSightingId'
    $sourceSightingUrl = Get-OptionalValue -Data $Data -Name 'SourceSightingUrl'
    $sourceSighting = Format-SourceSighting -TenantSubject $sourceSightingTenantSubject -SightingId $sourceSightingId -SightingUrl $sourceSightingUrl
    $notes = Get-OptionalList -Data $Data -Name 'Notes'
    $conversationId = Get-OptionalValue -Data $Data -Name 'ConversationId'

    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add('## Ticket Summary')
    [void]$lines.Add("- Ticket ID: $ticketId")
    [void]$lines.Add("- Tenant Subject: $tenantSubject")
    if (-not [string]::IsNullOrWhiteSpace($ticketUrl)) {
        [void]$lines.Add("- Ticket Link: $ticketUrl")
    }
    if (-not [string]::IsNullOrWhiteSpace($parentId)) {
        [void]$lines.Add("- Parent ID: $parentId")
    }
    if (-not [string]::IsNullOrWhiteSpace($sourceSighting)) {
        [void]$lines.Add("- Source Sighting: $sourceSighting")
    }
    [void]$lines.Add('')
    [void]$lines.Add('## Analysis')
    [void]$lines.Add("- Issue description: $issueDescription")
    [void]$lines.Add("- Failure signature: $(if ([string]::IsNullOrWhiteSpace($failureSignature)) { 'Not explicitly stated' } else { $failureSignature })")
    [void]$lines.Add("- Duplicated configuration: $reproduction")
    [void]$lines.Add("- Final solution: $(if ([string]::IsNullOrWhiteSpace($finalSolution)) { 'Not explicitly stated' } else { $finalSolution })")
    [void]$lines.Add("- Impacted platform: $affectedProducts")
    [void]$lines.Add("- Conclusion: $(if ([string]::IsNullOrWhiteSpace($conclusion)) { 'Not explicitly classified' } else { $conclusion })")
    [void]$lines.Add('')
    [void]$lines.Add('## Root Cause')
    [void]$lines.Add($rootCause)
    [void]$lines.Add('')
    [void]$lines.Add('## Notes')

    $metadataLines = @(
        $(if (-not [string]::IsNullOrWhiteSpace($release)) { "- Release: $release" }),
        $(if (-not [string]::IsNullOrWhiteSpace($status)) { "- Status: $status" }),
        $(if (-not [string]::IsNullOrWhiteSpace($reason)) { "- Reason: $reason" }),
        $(if (-not [string]::IsNullOrWhiteSpace($owner)) { "- Owner: $owner" }),
        $(if (-not [string]::IsNullOrWhiteSpace($submittedDate)) { "- Submitted Date: $submittedDate" }),
        $(if (-not [string]::IsNullOrWhiteSpace($component)) { "- Component: $component" })
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($line in $metadataLines) {
        [void]$lines.Add($line)
    }

    if ($notes.Count -eq 0 -and $metadataLines.Count -eq 0) {
        [void]$lines.Add('- No additional notes.')
    }
    else {
        foreach ($note in $notes) {
            [void]$lines.Add("- $note")
        }
    }

    [void]$lines.Add('')
    [void]$lines.Add("The question was answered based on the following tenant_subject: $tenantSubject")
    if (-not [string]::IsNullOrWhiteSpace($conversationId)) {
        [void]$lines.Add('')
        [void]$lines.Add("[Click here to provide Co-Design HSD MCP Feedback](mailto:Co-Design-MCPs@intel.com?subject=Co-Design%20HSD%20MCP%20Tools%20Feedback%20$conversationId)")
    }

    return ($lines -join [Environment]::NewLine)
}

if (-not (Test-Path -LiteralPath $InputJson)) {
    throw "Input JSON not found: $InputJson"
}

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    throw "Output directory not found: $OutputDirectory"
}

$analysisData = Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json
$ticketId = Get-RequiredValue -Data $analysisData -Name 'TicketId'
$sourceSightingTenantSubject = Get-OptionalValue -Data $analysisData -Name 'SourceSightingTenantSubject'
$sourceSightingId = Get-OptionalValue -Data $analysisData -Name 'SourceSightingId'
$sourceSightingUrl = Get-OptionalValue -Data $analysisData -Name 'SourceSightingUrl'
$sourceSighting = Format-SourceSighting -TenantSubject $sourceSightingTenantSubject -SightingId $sourceSightingId -SightingUrl $sourceSightingUrl
$dateString = Get-OptionalValue -Data $analysisData -Name 'Date'
if ([string]::IsNullOrWhiteSpace($dateString)) {
    $dateString = Get-Date -Format 'yyyyMMdd'
}
if ($dateString -notmatch '^\d{8}$') {
    throw "Date must use YYYYMMDD format. Received: $dateString"
}

$markdownPath = Join-Path $OutputDirectory ("HSD_{0}_analysis_{1}.md" -f $ticketId, $dateString)
$markdownContent = New-MarkdownDocument -Data $analysisData
Set-Content -LiteralPath $markdownPath -Value $markdownContent -Encoding UTF8

$commentsParts = @(
    $(Get-OptionalValue -Data $analysisData -Name 'Comments'),
    $(Get-OptionalValue -Data $analysisData -Name 'Reason')
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$notes = Get-OptionalList -Data $analysisData -Name 'Notes'
$combinedComments = Join-NonEmpty -Values @($commentsParts + $notes)

$workbookInput = [pscustomobject]@{
    TicketId = $ticketId
    Date = $dateString
    IssueTitle = Get-RequiredValue -Data $analysisData -Name 'IssueTitle'
    Domain = Get-OptionalValue -Data $analysisData -Name 'Domain'
    ProblemDescription = Get-RequiredValue -Data $analysisData -Name 'ProblemDescription'
    SystemConfigurationAndReproductionStep = Get-RequiredValue -Data $analysisData -Name 'SystemConfigurationAndReproductionStep'
    RootCause = Get-RequiredValue -Data $analysisData -Name 'RootCause'
    FinalSolution = Get-OptionalValue -Data $analysisData -Name 'FinalSolution'
    AffectedProducts = Get-RequiredValue -Data $analysisData -Name 'AffectedProducts'
    Severity = Get-OptionalValue -Data $analysisData -Name 'Severity'
    Owner = Get-OptionalValue -Data $analysisData -Name 'Owner'
    Component = Get-OptionalValue -Data $analysisData -Name 'Component'
    Status = Get-OptionalValue -Data $analysisData -Name 'Status'
    SubmittedDate = Get-OptionalValue -Data $analysisData -Name 'SubmittedDate'
    Conclusion = Normalize-Conclusion -Value (Get-OptionalValue -Data $analysisData -Name 'Conclusion')
    Comments = $combinedComments
    SourceSighting = $sourceSighting
}

$tempWorkbookInputPath = Join-Path $OutputDirectory ("hsd_{0}_workbook_input_{1}.json" -f $ticketId, $dateString)
$workbookInput | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tempWorkbookInputPath -Encoding UTF8

$generatorPath = Join-Path $PSScriptRoot 'generate-hsd-workbook.ps1'
$generatorParams = @{
    InputJson = $tempWorkbookInputPath
    OutputDirectory = $OutputDirectory
    DeleteInputJson = $true
}
if (-not [string]::IsNullOrWhiteSpace($TemplatePath)) {
    $generatorParams.TemplatePath = $TemplatePath
}

$workbookResultJson = & $generatorPath @generatorParams
$workbookResult = $workbookResultJson | ConvertFrom-Json

if ($DeleteInputJson) {
    Remove-Item -LiteralPath $InputJson -Force
}

$result = [pscustomobject]@{
    TicketId = $ticketId
    TenantSubject = Get-RequiredValue -Data $analysisData -Name 'TenantSubject'
    MarkdownPath = $markdownPath
    WorkbookPath = [string]$workbookResult.OutputPath
    TemplateUsed = [string]$workbookResult.TemplateUsed
    SourceSighting = $sourceSighting
}

$result | ConvertTo-Json -Depth 4
