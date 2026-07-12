param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ProjectId,
    [string]$ObjectPath = "CommonModules/Orders.bsl"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

function Get-Api([string]$Path) {
    Invoke-RestMethod -Uri "$BaseUrl$Path"
}

function Post-Api([string]$Path, [object]$Body = $null) {
    $params = @{ Method = "Post"; Uri = "$BaseUrl$Path" }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body | ConvertTo-Json -Depth 10
    }
    Invoke-RestMethod @params
}

$health = Get-Api "/health"
if ($health.status -ne "ok") { throw "Backend health is not ok" }
$mcpHealth = Get-Api "/api/v1/system/mcp/health"
if ($mcpHealth.status -ne "ok") { throw "EDT MCP initialize failed" }
$toolsResponse = Get-Api "/api/v1/system/mcp/tools"
$tools = @($toolsResponse.tools)
$envValues = @{}
$envPath = Join-Path $repo ".env"
if (Test-Path -LiteralPath $envPath) {
    Get-Content -LiteralPath $envPath | ForEach-Object {
        if ($_ -match "^\s*([^#=][^=]*)=(.*)$") { $envValues[$matches[1].Trim()] = $matches[2].Trim() }
    }
}
$searchName = if ($envValues["MCP_PATCH_SEARCH_TOOL"]) { $envValues["MCP_PATCH_SEARCH_TOOL"] } else { "search_code" }
$searchTool = $tools | Where-Object { $_.name -eq $searchName } | Select-Object -First 1
if (-not $searchTool) { throw "Configured MCP patch search tool '$searchName' was not discovered" }
if ($searchTool.mode -ne "read-only" -or $searchTool.category -ne "code.search") {
    throw "Configured MCP patch search tool is not a read-only code.search tool"
}

if ($envValues["MCP_PROJECTS_TOOL"]) {
    $sync = Post-Api "/api/v1/projects/sync"
    if ([int]$sync.synced -lt 1) { throw "EDT project sync returned no projects" }
}
if (-not $ProjectId) {
    $projects = @(Get-Api "/api/v1/projects")
    if ($projects.Count -lt 1) { throw "No synchronized 1C project is available" }
    $ProjectId = $projects[0].id
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$proposal = Post-Api "/api/v1/patch-proposals" @{
    projectId = $ProjectId
    title = "EDT live acceptance $stamp"
    summary = "Read-only source search and impact evidence"
    sourceRevision = "edt-live-$stamp"
    files = @(@{ path = $ObjectPath; original = "A`n"; proposed = "B`n" })
}
$impact = Post-Api "/api/v1/patch-proposals/$($proposal.id)/impact/mcp"
if ($impact.status -ne "analyzed_mcp") { throw "EDT MCP search did not complete" }
if (@($impact.impact | Where-Object { $_.risk -eq "evidenced" }).Count -lt 1) {
    throw "EDT MCP search returned no evidenced impact"
}

Write-Output "EDT live acceptance passed: MCP initialize, read-only $searchName discovery, project sync and source impact evidence verified."
