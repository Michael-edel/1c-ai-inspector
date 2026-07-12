param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$CodeTaskId,
    [string]$QueryTaskId,
    [string]$AuditTaskId
)

$ErrorActionPreference = "Stop"

function Get-Api([string]$Path) {
    Invoke-RestMethod -Uri "$BaseUrl$Path"
}

function Assert-CompletedTask([string]$TaskId, [string]$Label) {
    if (-not $TaskId) { return }

    $state = Get-Api "/api/v1/tasks/$TaskId"
    if ($state.status -ne "completed" -or -not $state.resultReady) {
        throw "$Label task is not completed: $($state.status)"
    }

    $audit = Get-Api "/api/v1/tasks/$TaskId/audit"
    foreach ($call in @($audit.tool_calls)) {
        if ($call.mode -ne "read-only") {
            throw "$Label task contains non-read-only tool call: $($call.toolName)"
        }
    }

    $report = Get-Api "/api/v1/tasks/$TaskId/report"
    foreach ($finding in @($report.findings)) {
        if (@($finding.evidence).Count -eq 0) {
            throw "$Label task contains a finding without evidence"
        }
    }
}

$health = Get-Api "/health"
if ($health.status -ne "ok") { throw "Backend health is not ok" }

$ready = Get-Api "/api/v1/system/ready"
if ($ready.status -ne "ready" -or $ready.database -ne "ok") {
    throw "System is not ready"
}

$tools = @(Get-Api "/api/v1/system/mcp/tools").tools
if ($tools.Count -lt 8) { throw "Expected at least 8 discovered tools" }
if ($tools | Where-Object { $_.mode -ne "read-only" }) {
    throw "A non-read-only MCP tool was discovered"
}
if ($tools | Where-Object { $_.name -eq "execute_query" }) {
    throw "execute_query must remain unpublished"
}

$sync = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/projects/sync"
if ($sync.synced -lt 1) { throw "Project sync returned no projects" }
if (@(Get-Api "/api/v1/projects").Count -lt 1) { throw "No projects are available" }

Assert-CompletedTask $CodeTaskId "Code Assistant"
Assert-CompletedTask $QueryTaskId "Query Agent"
Assert-CompletedTask $AuditTaskId "Audit Agent"

Write-Output "v0.1 acceptance passed"
