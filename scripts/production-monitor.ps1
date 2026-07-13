param(
    [string]$BaseUrl = "https://inspector.michael.kz",
    [ValidateRange(1, 64)][int]$MinimumTools = 8
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd("/")

$healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$base/health"
$health = $healthResponse.Content | ConvertFrom-Json
if ($health.status -ne "ok") { throw "Production health is not ok" }
foreach ($header in @("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy", "X-Request-ID")) {
    if (-not $healthResponse.Headers[$header]) { throw "Missing security header: $header" }
}

$readiness = Invoke-RestMethod -Uri "$base/api/v1/system/readiness"
if ($readiness.status -ne "ready") { throw "Production readiness is not ready" }

$policy = Invoke-RestMethod -Uri "$base/api/v1/system/policy"
$discoveredTools = @($policy.discoveredTools)
if ($discoveredTools.Count -lt $MinimumTools) { throw "Expected at least $MinimumTools discovered tools" }
if (@($policy.publishedTools) -contains "execute_query") { throw "Forbidden execute_query tool is published" }

$projects = Invoke-RestMethod -Uri "$base/api/v1/projects"
if ($projects.Count -lt 1) { throw "No synchronized projects are available" }
$history = Invoke-RestMethod -Uri "$base/api/v1/tasks"
$historyProperties = @($history | ForEach-Object { $_.PSObject.Properties.Name })
foreach ($forbiddenProperty in @("request", "requestJson", "result", "resultJson")) {
    if ($historyProperties -contains $forbiddenProperty) { throw "Task history exposes forbidden property: $forbiddenProperty" }
}

Write-Output "Production monitor passed: health=ok readiness=ready discoveredTools=$($discoveredTools.Count) projects=$($projects.Count) taskHistory=$($history.Count)."
