param(
    [Parameter(Mandatory = $true)]
    [string]$ArticleId,

    [string]$OutDir,

    [switch]$ForceCurlDirect
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $OutDir) {
    $OutDir = Join-Path (Join-Path (Split-Path -Parent $scriptRoot) 'out') $ArticleId
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$rawPath = Join-Path $OutDir "hsd_${ArticleId}_raw.json"
$extractPath = Join-Path $OutDir "hsd_${ArticleId}_extracted.json"
$textPath = Join-Path $OutDir "hsd_${ArticleId}_extracted.txt"
$pythonScript = Join-Path $scriptRoot 'extract_hsd_article.py'

function Invoke-PythonFetch {
    param([string]$TargetPath)

    $code = @"
import json
import sys

try:
    import truststore
    truststore.inject_into_ssl()
    import requests
    from requests_kerberos import HTTPKerberosAuth
except Exception as exc:
    print(f"IMPORT_ERROR: {type(exc).__name__}: {exc}")
    sys.exit(10)

url = "https://hsdes-api.intel.com/rest/article/$ArticleId"
r = requests.get(url, auth=HTTPKerberosAuth(), headers={"Content-type": "application/json"}, timeout=60)
print(f"PYTHON_STATUS={r.status_code}")
if r.headers.get("content-type", "").lower().startswith("text/html"):
    print("PYTHON_HTML_RESPONSE=True")
r.raise_for_status()
with open(r"$TargetPath", "w", encoding="utf-8") as f:
    json.dump(r.json(), f, ensure_ascii=False, indent=2)
"@
    $tmp = Join-Path $OutDir "fetch_hsd_${ArticleId}.py"
    Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8
    py $tmp
    $script:LastFetchExit = $LASTEXITCODE
}

function Invoke-CurlDirect {
    param([string]$TargetPath)

    $headersPath = Join-Path $OutDir "hsd_${ArticleId}_headers.txt"
    curl.exe --noproxy "*" --negotiate -u : -L -s -D $headersPath "https://hsdes-api.intel.com/rest/article/$ArticleId" -o $TargetPath
    $script:LastFetchExit = $LASTEXITCODE
    Write-Output "CURL_DIRECT_EXIT=$script:LastFetchExit"
    if (Test-Path -LiteralPath $headersPath) {
        Get-Content -LiteralPath $headersPath | Select-Object -First 20
    }
}

if (-not $ForceCurlDirect) {
    Write-Output '=== PYTHON_KERBEROS_FETCH ==='
    Invoke-PythonFetch -TargetPath $rawPath
    $pythonExit = $script:LastFetchExit
    Write-Output "PYTHON_FETCH_EXIT=$pythonExit"
} else {
    $pythonExit = 99
}

if ($ForceCurlDirect -or $pythonExit -ne 0) {
    Write-Output '=== CURL_DIRECT_FALLBACK ==='
    Invoke-CurlDirect -TargetPath $rawPath
    $curlExit = $script:LastFetchExit
    if ($curlExit -ne 0) {
        exit $curlExit
    }
}

if (-not (Test-Path -LiteralPath $rawPath)) {
    throw "Raw article file was not created: $rawPath"
}

Write-Output '=== EXTRACT_FIELDS ==='
py $pythonScript --raw $rawPath --article-id $ArticleId --json-out $extractPath --text-out $textPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output "RAW_PATH=$rawPath"
Write-Output "EXTRACTED_JSON=$extractPath"
Write-Output "EXTRACTED_TEXT=$textPath"
exit 0
