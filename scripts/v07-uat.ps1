param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [Parameter(Mandatory = $true)][string]$CodeTaskId,
    [Parameter(Mandatory = $true)][string]$QueryTaskId,
    [Parameter(Mandatory = $true)][string]$AuditTaskId
)

$ErrorActionPreference = "Stop"

function Get-Api([string]$Path) {
    Invoke-RestMethod -Uri "$BaseUrl$Path"
}

function Assert-CompletedReadOnlyTask([string]$TaskId, [string]$Label) {
    $state = Get-Api "/api/v1/tasks/$TaskId"
    if ($state.status -ne "completed" -or -not $state.resultReady) {
        throw "$Label task is not completed: $($state.status)"
    }

    $audit = Get-Api "/api/v1/tasks/$TaskId/audit"
    $calls = @($audit.tool_calls)
    if ($calls.Count -eq 0) {
        throw "$Label task has no recorded MCP tool calls"
    }
    foreach ($call in $calls) {
        if ($call.mode -ne "read-only") {
            throw "$Label task contains non-read-only tool call: $($call.toolName)"
        }
        if ($call.toolName -eq "execute_query") {
            throw "$Label task attempted forbidden execute_query"
        }
    }
    $modelUsage = @($audit.model_usage)
    if ($modelUsage.Count -eq 0) {
        throw "$Label task has no model usage audit"
    }
    foreach ($usage in $modelUsage) {
        foreach ($property in @("model", "cachedInputTokens", "durationMs", "pricingSource")) {
            if ($usage.PSObject.Properties.Name -notcontains $property) {
                throw "$Label model usage is missing $property"
            }
        }
        if ($usage.durationMs -lt 0 -or $usage.cachedInputTokens -lt 0) {
            throw "$Label model usage contains a negative telemetry value"
        }
    }

    $report = Get-Api "/api/v1/tasks/$TaskId/report"
    if ($report.status -ne "completed") {
        throw "$Label report is not completed: $($report.status)"
    }
    foreach ($property in @("model", "cachedInputTokens", "durationMs", "pricingSource")) {
        if ($report.modelUsage.PSObject.Properties.Name -notcontains $property) {
            throw "$Label report modelUsage is missing $property"
        }
    }
    $findings = @($report.findings)
    $persisted = @($report.persistedFindings)
    if ($findings.Count -ne $persisted.Count) {
        throw "$Label report/persisted findings mismatch: $($findings.Count)/$($persisted.Count)"
    }
    foreach ($finding in $persisted) {
        if (@($finding.evidence).Count -eq 0) {
            throw "$Label contains a persisted finding without evidence"
        }
    }

    Write-Output "$Label passed: calls=$($calls.Count), findings=$($persisted.Count)"
}

$health = Get-Api "/health"
if ($health.status -ne "ok") { throw "Backend health is not ok" }

$readiness = Get-Api "/api/v1/system/readiness"
if ($readiness.status -ne "ready") { throw "Readiness is not ready: $($readiness.reasons -join ', ')" }

$policy = Get-Api "/api/v1/system/policy"
if (@($policy.discoveredTools).Count -lt 8) { throw "Expected at least 8 discovered tools" }
if ($policy.publishedTools -contains "execute_query") { throw "execute_query must remain unpublished" }

$projects = @(Get-Api "/api/v1/projects")
if ($projects.Count -lt 1) { throw "No projects are available" }

Assert-CompletedReadOnlyTask $CodeTaskId "Code Assistant"
Assert-CompletedReadOnlyTask $QueryTaskId "Query Agent"
Assert-CompletedReadOnlyTask $AuditTaskId "Audit Agent"

Write-Output "v0.7 UAT passed: health, readiness, policy, three agents, read-only calls, reports and persisted evidence verified."
