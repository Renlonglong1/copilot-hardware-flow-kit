param(
    [Parameter(Mandatory = $true)]
    [string]$To,

    [Parameter(Mandatory = $true)]
    [string]$Subject,

    [Parameter(Mandatory = $true)]
    [string]$Body,

    [string[]]$Attachments = @(),

    [switch]$IncludeMlcResults,

    [switch]$Send,

    [int]$StartupWaitSeconds = 30,

    [string]$FallbackDir
)

$ErrorActionPreference = 'Stop'

if (-not $FallbackDir) {
    $scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $FallbackDir = Join-Path (Split-Path -Parent $scriptRoot) 'out'
}
New-Item -ItemType Directory -Path $FallbackDir -Force | Out-Null

function Resolve-NotificationAttachments {
    param([string[]]$RequestedAttachments)

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($attachment in $RequestedAttachments) {
        if ($attachment -and (Test-Path -LiteralPath $attachment)) {
            $path = (Resolve-Path -LiteralPath $attachment).Path
            if (-not $resolved.Contains($path)) {
                $resolved.Add($path)
            }
        }
    }
    return $resolved
}

if ($IncludeMlcResults) {
    $reportAttachment = @(
        $Attachments | Where-Object {
            $_ -and (Test-Path -LiteralPath $_) -and ([IO.Path]::GetExtension($_) -eq '.md')
        }
    ) | Select-Object -First 1
    if (-not $reportAttachment) {
        throw 'INCLUDE_MLC_RESULTS_REQUIRES_A_MARKDOWN_REPORT_ATTACHMENT'
    }

    $reportDir = Split-Path -Parent (Resolve-Path -LiteralPath $reportAttachment).Path
    $mlcResult = Get-ChildItem -LiteralPath $reportDir -Recurse -File -Filter 'host_mlc_results.log' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $mlcResult) {
        throw "MLC_RESULT_LOG_NOT_FOUND_UNDER_REPORT_DIRECTORY: $reportDir"
    }

    $Attachments = @($Attachments) + $mlcResult.FullName
    Write-Output "MLC_RESULT_ATTACHMENT=$($mlcResult.FullName)"
}

$Attachments = Resolve-NotificationAttachments -RequestedAttachments $Attachments

function Get-OutlookExePath {
    $candidates = @(
        'C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE',
        'C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $cmd = Get-Command OUTLOOK.EXE -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Get-OutlookApplication {
    try {
        return [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
    } catch {
        return $null
    }
}

function New-OutlookApplicationWithRetry {
    $outlook = Get-OutlookApplication
    if ($outlook) {
        $script:OutlookComSource = 'ActiveObject'
        return $outlook
    }

    try {
        $outlook = New-Object -ComObject Outlook.Application
        $script:OutlookComSource = 'NewObject'
        return $outlook
    } catch {
        $script:OutlookInitialError = "$($_.Exception.HResult) $($_.Exception.Message)"
    }

    $outlookExe = Get-OutlookExePath
    if (-not $outlookExe) {
        throw 'OUTLOOK_EXE_NOT_FOUND'
    }

    $script:StartedOutlook = $outlookExe
    Start-Process -FilePath $outlookExe -WindowStyle Minimized | Out-Null

    $deadline = (Get-Date).AddSeconds($StartupWaitSeconds)
    do {
        Start-Sleep -Seconds 2
        $outlook = Get-OutlookApplication
        if ($outlook) {
            $script:OutlookComSource = 'ActiveObjectAfterStart'
            return $outlook
        }
        try {
            $outlook = New-Object -ComObject Outlook.Application
            $script:OutlookComSource = 'NewObjectAfterStart'
            return $outlook
        } catch {
            $lastError = "$($_.Exception.HResult) $($_.Exception.Message)"
        }
    } while ((Get-Date) -lt $deadline)

    throw "OUTLOOK_COM_UNAVAILABLE_AFTER_START: $lastError"
}

function ConvertTo-EmlSafe {
    param([string]$Value)
    return (($Value -replace "`r", ' ') -replace "`n", ' ')
}

function ConvertTo-NotificationHtmlText {
    param([Parameter(Mandatory = $true)][string]$Text)

    $encoded = [System.Net.WebUtility]::HtmlEncode($Text)
    return [regex]::Replace(
        $encoded,
        'https?://[^\s<]+',
        {
            param($match)
            $url = $match.Value
            "<a href=""$url"" style=""color:#0969da;"">$url</a>"
        }
    )
}

function ConvertTo-NotificationHtml {
    param([Parameter(Mandatory = $true)][string]$Text)

    $html = New-Object System.Text.StringBuilder
    [void]$html.Append('<html><body style="font-family:Segoe UI,Microsoft YaHei,Arial,sans-serif;font-size:10.5pt;color:#24292f;line-height:1.55;">')
    $listOpen = $false

    foreach ($rawLine in ($Text -split "\r?\n")) {
        $line = $rawLine.Trim()
        if (-not $line) {
            if ($listOpen) {
                [void]$html.Append('</ul>')
                $listOpen = $false
            }
            continue
        }

        if ($line -match '^[\p{IsCJKUnifiedIdeographs}]{2,10}$') {
            if ($listOpen) {
                [void]$html.Append('</ul>')
                $listOpen = $false
            }
            [void]$html.AppendFormat('<h2 style="font-size:12pt;margin:18px 0 6px;border-bottom:1px solid #d0d7de;padding-bottom:4px;">{0}</h2>', (ConvertTo-NotificationHtmlText -Text $line))
            continue
        }

        if ($line -match '^\-\s+(.+)$') {
            if (-not $listOpen) {
                [void]$html.Append('<ul style="margin:4px 0 10px;padding-left:22px;">')
                $listOpen = $true
            }
            [void]$html.AppendFormat('<li style="margin:3px 0;">{0}</li>', (ConvertTo-NotificationHtmlText -Text $Matches[1]))
            continue
        }

        if ($listOpen) {
            [void]$html.Append('</ul>')
            $listOpen = $false
        }

        if ($line -match '^(HSD/IPS ID|标题|Owner|任务类型)\s*:\s*(.+)$') {
            [void]$html.AppendFormat(
                '<p style="margin:3px 0;"><strong>{0}:</strong> {1}</p>',
                [System.Net.WebUtility]::HtmlEncode($Matches[1]),
                (ConvertTo-NotificationHtmlText -Text $Matches[2])
            )
        } else {
            [void]$html.AppendFormat('<p style="margin:6px 0;">{0}</p>', (ConvertTo-NotificationHtmlText -Text $line))
        }
    }

    if ($listOpen) {
        [void]$html.Append('</ul>')
    }
    [void]$html.Append('</body></html>')
    return $html.ToString()
}

function Write-FallbackFiles {
    param([string]$Reason)

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $baseName = "owner_notification_$stamp"
    $bodyPath = Join-Path $FallbackDir "$baseName.txt"
    $emlPath = Join-Path $FallbackDir "$baseName.eml"

    $fallbackText = @(
        "TO: $To",
        "SUBJECT: $Subject",
        "REASON: $Reason",
        '',
        $Body,
        '',
        'ATTACHMENTS:',
        ($Attachments -join "`r`n")
    ) -join "`r`n"
    Set-Content -LiteralPath $bodyPath -Value $fallbackText -Encoding UTF8

    $eml = @(
        "To: $(ConvertTo-EmlSafe $To)",
        "Subject: $(ConvertTo-EmlSafe $Subject)",
        'X-Unsent: 1',
        'Content-Type: text/plain; charset=utf-8',
        '',
        $Body,
        '',
        'Attachments to add manually:',
        ($Attachments -join "`r`n")
    ) -join "`r`n"
    Set-Content -LiteralPath $emlPath -Value $eml -Encoding UTF8

    Write-Output 'NOTIFICATION_FALLBACK_CREATED=True'
    Write-Output "FALLBACK_REASON=$Reason"
    Write-Output "FALLBACK_BODY=$bodyPath"
    Write-Output "FALLBACK_EML=$emlPath"
}

try {
    $outlook = New-OutlookApplicationWithRetry
} catch {
    Write-FallbackFiles -Reason $_.Exception.Message
    exit 2
}

if ($script:OutlookInitialError) {
    Write-Output "OUTLOOK_NEW_COM_INITIAL_FAIL=$script:OutlookInitialError"
}
if ($script:StartedOutlook) {
    Write-Output "STARTED_OUTLOOK=$script:StartedOutlook"
}
Write-Output "OUTLOOK_COM_SOURCE=$script:OutlookComSource"

try {
    $mail = $outlook.CreateItem(0)
    $mail.To = $To
    $mail.Subject = $Subject
    $mail.HTMLBody = ConvertTo-NotificationHtml -Text $Body

    foreach ($attachment in $Attachments) {
        [void]$mail.Attachments.Add($attachment)
    }

    if ($Send) {
        $mail.Send()
        Write-Output "NOTIFICATION_SENT=True"
        Write-Output "TO=$To"
    } else {
        $mail.Display()
        Write-Output "NOTIFICATION_DRAFT_DISPLAYED=True"
        Write-Output "TO=$To"
    }
} catch {
    $reason = "OUTLOOK_MAIL_OPERATION_FAILED: $($_.Exception.Message)"
    if ($_.Exception.Message -match 'dialog box is open') {
        $reason += ' Close any Outlook modal dialog/login/profile/security prompt and retry.'
    }
    Write-FallbackFiles -Reason $reason
    exit 3
}
