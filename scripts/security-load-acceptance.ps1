param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [ValidateRange(1, 200)][int]$Count = 20
)

$ErrorActionPreference = "Stop"
$healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health"
foreach ($header in @("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy", "X-Request-ID")) {
    if (-not $healthResponse.Headers[$header]) { throw "Missing security header: $header" }
}
if ($healthResponse.Headers["X-Content-Type-Options"] -ne "nosniff") { throw "Invalid content type security header" }
if ($healthResponse.Headers["X-Frame-Options"] -ne "DENY") { throw "Invalid frame security header" }

$metricsSucceeded = $false
try {
    Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/metrics" | Out-Null
    $metricsSucceeded = $true
} catch {
    if (-not $_.Exception.Response) { throw }
    if ([int]$_.Exception.Response.StatusCode -ne 401) { throw }
}
if ($metricsSucceeded) { throw "Unauthenticated metrics request unexpectedly succeeded" }

$policy = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "..\mcp_policy.yaml")
if ($policy -match "(?im)^\s*mode:\s*write\s*$") { throw "Write tool found in published policy" }
$dockerfile = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot "..\backend\Dockerfile")
if ($dockerfile -notmatch "USER app") {
    throw "Backend container is not configured for non-root execution"
}

$processes = @(
    1..$Count | ForEach-Object {
        Start-Process -FilePath "curl.exe" -ArgumentList @(
            "--fail", "--silent", "--show-error", "--output", "NUL", "$BaseUrl/health"
        ) -WindowStyle Hidden -PassThru
    }
)
foreach ($process in $processes) {
    if (-not $process.WaitForExit(30000) -or $process.ExitCode -ne 0) {
        throw "Concurrent health request failed"
    }
}
Write-Output "Security/load acceptance passed: headers, metrics auth, read-only policy, non-root backend and $Count concurrent health requests verified."
