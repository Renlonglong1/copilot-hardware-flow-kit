param(
    [string]$Root = $PSScriptRoot,
    [int]$Port = 18080
)

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add(("http://localhost:{0}/" -f $Port))

try {
    $listener.Start()
}
catch {
    Write-Host ""
    Write-Host ("Unable to start RAS Register Decoder on port {0}." -f $Port) -ForegroundColor Red
    Write-Host "The port may already be in use. Close the other instance and try again." -ForegroundColor Yellow
    exit 1
}

Start-Process ("http://localhost:{0}/" -f $Port)
Write-Host ""
Write-Host ("RAS Register Decoder is running at http://localhost:{0}/" -f $Port) -ForegroundColor Green
Write-Host "Close this window to stop the local server." -ForegroundColor Yellow

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $relativePath = [Uri]::UnescapeDataString($context.Request.Url.AbsolutePath.TrimStart('/'))
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            $relativePath = "index.html"
        }

        $relativePath = $relativePath -replace '/', '\'
        $filePath = [System.IO.Path]::GetFullPath((Join-Path $Root $relativePath))
        $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'

        if (-not $filePath.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            $context.Response.StatusCode = 404
            $bytes = [System.Text.Encoding]::UTF8.GetBytes("Not found")
            $context.Response.ContentType = "text/plain; charset=utf-8"
        }
        else {
            $bytes = [System.IO.File]::ReadAllBytes($filePath)
            switch ([System.IO.Path]::GetExtension($filePath).ToLowerInvariant()) {
                ".html" { $context.Response.ContentType = "text/html; charset=utf-8" }
                ".js" { $context.Response.ContentType = "application/javascript; charset=utf-8" }
                ".css" { $context.Response.ContentType = "text/css; charset=utf-8" }
                ".json" { $context.Response.ContentType = "application/json; charset=utf-8" }
                default { $context.Response.ContentType = "application/octet-stream" }
            }
        }

        $context.Response.ContentLength64 = $bytes.Length
        $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        $context.Response.Close()
    }
}
finally {
    if ($listener.IsListening) {
        $listener.Stop()
    }
    $listener.Close()
}
