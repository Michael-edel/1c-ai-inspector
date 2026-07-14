param(
    [string]$BaseUrl = "https://inspector.michael.kz",
    [ValidateRange(1, 64)][int]$MinimumTools = 8
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd("/")

$rootResponse = Invoke-WebRequest -UseBasicParsing -Uri "$base/"
if ([string]$rootResponse.Headers["Cache-Control"] -notmatch "(?:^|,)\s*no-store(?:,|$)") {
    throw "Production HTML shell is cacheable"
}
if ($rootResponse.Content -match "/@vite/client|/src/main\.tsx") {
    throw "Production HTML exposes Vite development entrypoints"
}

$healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$base/health"
$health = $healthResponse.Content | ConvertFrom-Json
if ($health.status -ne "ok") { throw "Production health is not ok" }
foreach ($header in @("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy", "X-Request-ID")) {
    if (-not $healthResponse.Headers[$header]) { throw "Missing security header: $header" }
}
if ($base.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
    $hsts = [string]$healthResponse.Headers["Strict-Transport-Security"]
    $csp = [string]$healthResponse.Headers["Content-Security-Policy"]
    if ($hsts -notmatch "(?:^|;)\s*max-age=\d+") { throw "Missing or invalid Strict-Transport-Security header" }
    if (
        $csp -notmatch "default-src 'self'" -or
        $csp -notmatch "font-src 'self'" -or
        $csp -notmatch "style-src 'self'" -or
        $csp -notmatch "frame-ancestors 'none'" -or
        $csp -notmatch "object-src 'none'" -or
        $csp -match "https?://"
    ) {
        throw "Missing or invalid Content-Security-Policy header"
    }
}

$readiness = Invoke-RestMethod -Uri "$base/api/v1/system/readiness"
if ($readiness.status -ne "ready") { throw "Production readiness is not ready" }

$policy = Invoke-RestMethod -Uri "$base/api/v1/system/policy"
$discoveredTools = @($policy.discoveredTools)
if ($discoveredTools.Count -lt $MinimumTools) { throw "Expected at least $MinimumTools discovered tools" }
foreach ($forbiddenTool in @("execute_query", "get_event_log")) {
    if (@($policy.publishedTools) -contains $forbiddenTool) { throw "Forbidden $forbiddenTool tool is published" }
}

$traffic = Invoke-RestMethod -Uri "$base/api/v1/system/traffic"
if ($traffic.warningBytes -ne 5000000000 -or $traffic.criticalBytes -ne 8000000000 -or $traffic.hardLimitBytes -ne 9800000000) {
    throw "Production traffic thresholds do not match 5/8/9.8 GB"
}
if (@("normal", "warning", "critical", "blocked") -notcontains $traffic.level) {
    throw "Production traffic level is invalid"
}
if ($traffic.accountedBytes -gt $traffic.hardLimitBytes -or $traffic.remainingBytes -lt 0) {
    throw "Production traffic counter exceeds its hard limit"
}

$costs = Invoke-RestMethod -Uri "$base/api/v1/system/costs"
if ($costs.currency -ne "KZT" -or $costs.estimatedCostKzt -lt 0 -or $costs.usdKztRate -le 0) {
    throw "Production model cost accounting is invalid"
}
if ($costs.pricing.model -ne "gpt-5.6-luna" -or $costs.pricing.inputPer1M -ne 1 -or $costs.pricing.cachedInputPer1M -ne 0.1 -or $costs.pricing.outputPer1M -ne 6) {
    throw "Production GPT-5.6 Luna pricing does not match the configured public tariff"
}
$costEstimate = Invoke-RestMethod -Uri "$base/api/v1/system/cost-estimate"
if ($costEstimate.model -ne "gpt-5.6-luna" -or $costEstimate.currency -ne "KZT" -or $costEstimate.estimateType -ne "upper-bound" -or $costEstimate.estimatedCostKzt -le 0) {
    throw "Production preflight cost confirmation estimate is invalid"
}

$projects = Invoke-RestMethod -Uri "$base/api/v1/projects"
if ($projects.Count -lt 1) { throw "No synchronized projects are available" }
$history = Invoke-RestMethod -Uri "$base/api/v1/tasks"
$historyProperties = @($history | ForEach-Object { $_.PSObject.Properties.Name })
foreach ($forbiddenProperty in @("request", "requestJson", "result", "resultJson")) {
    if ($historyProperties -contains $forbiddenProperty) { throw "Task history exposes forbidden property: $forbiddenProperty" }
}

Write-Output "Production monitor passed: health=ok readiness=ready discoveredTools=$($discoveredTools.Count) projects=$($projects.Count) taskHistory=$($history.Count) traffic=$($traffic.accountedBytes)/$($traffic.hardLimitBytes) modelCostKzt=$($costs.estimatedCostKzt)."
