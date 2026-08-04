[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$GeneratedDirectory = $(Join-Path (Split-Path -Parent $PSScriptRoot) 'generated'),

    [switch]$IncludeWorkbooks,

    [switch]$IncludeDocuments,

    [int]$OlderThanDays = 0
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $GeneratedDirectory)) {
    throw "Generated directory not found: $GeneratedDirectory"
}

$cutoffTime = if ($OlderThanDays -gt 0) {
    (Get-Date).AddDays(-1 * $OlderThanDays)
} else {
    $null
}

$patterns = @('*.json')
if ($IncludeWorkbooks) {
    $patterns += '*.xlsx'
}
if ($IncludeDocuments) {
    $patterns += '*.md'
}

$files = foreach ($pattern in $patterns) {
    Get-ChildItem -LiteralPath $GeneratedDirectory -File -Filter $pattern
}

if ($cutoffTime) {
    $files = $files | Where-Object { $_.LastWriteTime -lt $cutoffTime }
}

$removedFiles = New-Object System.Collections.Generic.List[string]
$skippedFiles = New-Object System.Collections.Generic.List[string]

foreach ($file in $files | Sort-Object FullName -Unique) {
    if ($PSCmdlet.ShouldProcess($file.FullName, 'Remove generated artifact')) {
        try {
            Remove-Item -LiteralPath $file.FullName -Force
            [void]$removedFiles.Add($file.FullName)
        }
        catch {
            [void]$skippedFiles.Add($file.FullName)
        }
    }
}

$result = [pscustomobject]@{
    GeneratedDirectory = $GeneratedDirectory
    IncludeWorkbooks = [bool]$IncludeWorkbooks
    IncludeDocuments = [bool]$IncludeDocuments
    OlderThanDays = $OlderThanDays
    RemovedCount = $removedFiles.Count
    RemovedFiles = $removedFiles
    SkippedCount = $skippedFiles.Count
    SkippedFiles = $skippedFiles
}

$result | ConvertTo-Json -Depth 4
