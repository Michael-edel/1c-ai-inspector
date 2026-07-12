param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ProjectId
)

$ErrorActionPreference = "Stop"

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

if (-not $ProjectId) {
    $projects = @(Get-Api "/api/v1/projects")
    if ($projects.Count -lt 1) { throw "No project is available for v0.3 acceptance" }
    $ProjectId = $projects[0].id
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$proposal = Post-Api "/api/v1/patch-proposals" @{
    projectId = $ProjectId
    title = "v0.3 acceptance $stamp"
    summary = "Evidence, validation, role and package acceptance flow"
    sourceRevision = "v0.3-acceptance-$stamp"
    files = @(@{
        path = "Documents/SalesOrder/Module.bsl"
        original = "Procedure Acceptance();`nEndProcedure;`n"
        proposed = "Procedure Acceptance();`n`tReturn True;`nEndProcedure;`n"
    })
}

$impact = Post-Api "/api/v1/patch-proposals/$($proposal.id)/impact" @{
    evidence = @(@{
        objectFqn = "Document.SalesOrder"
        relation = "object_module"
        sourceTool = "search_code"
        evidence = @("CommonModule.Orders.CheckOrder line 12")
    })
}
if ($impact.impact[0].risk -ne "evidenced") { throw "Impact evidence was not accepted" }

$source = Post-Api "/api/v1/patch-proposals/$($proposal.id)/revalidate" @{
    currentRevision = $proposal.sourceRevision
    files = @(@{
        path = "Documents/SalesOrder/Module.bsl"
        current = "Procedure Acceptance();`nEndProcedure;`n"
    })
}
if ($source.status -ne "valid") { throw "Source revalidation failed" }

$validation = Post-Api "/api/v1/patch-proposals/$($proposal.id)/validate"
if ($validation.status -ne "valid") { throw "Patch validation failed" }

$checkpoint = Post-Api "/api/v1/patch-proposals/$($proposal.id)/checkpoint"
if ($checkpoint.status -ne "checkpointed" -or $checkpoint.applied -ne $false) {
    throw "Checkpoint is invalid"
}

$reviewerBody = @{ actor = "v03-acceptance-reviewer"; role = "reviewer"; note = "Reviewer cannot approve." }
try {
    Post-Api "/api/v1/patch-proposals/$($proposal.id)/approve" $reviewerBody | Out-Null
    throw "Reviewer unexpectedly approved proposal"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
}

$approval = Post-Api "/api/v1/patch-proposals/$($proposal.id)/approve" @{
    actor = "v03-acceptance-maintainer"
    role = "maintainer"
    note = "Approved for workflow acceptance only; no apply operation exists."
}
if ($approval.status -ne "approved" -or $approval.applied -ne $false) {
    throw "Approval is invalid"
}

$package = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/api/v1/patch-proposals/$($proposal.id)/package"
if ($package.StatusCode -ne 200 -or $package.Headers["Content-Type"] -notlike "application/zip*") {
    throw "Proposal package response is invalid"
}

$events = Get-Api "/api/v1/patch-proposals/$($proposal.id)/events"
$eventTypes = @($events.events | ForEach-Object { $_.type })
$expected = @("created", "impact_analyzed", "source_revalidated", "validated", "checkpointed", "approved", "package_exported")
if ($eventTypes.Count -ne $expected.Count -or (Compare-Object $eventTypes $expected)) {
    throw "Unexpected v0.3 event log: $($eventTypes -join ', ')"
}

$rejected = Post-Api "/api/v1/patch-proposals" @{
    projectId = $ProjectId
    title = "v0.3 rejection acceptance $stamp"
    summary = "Reviewer rejection flow"
    files = @(@{ path = "CommonModules/Rejection.bsl"; original = "A`n"; proposed = "B`n" })
}
$rejection = Post-Api "/api/v1/patch-proposals/$($rejected.id)/reject" @{
    actor = "v03-acceptance-reviewer"
    role = "reviewer"
    note = "Rejected without applying the diff."
}
if ($rejection.status -ne "rejected" -or $rejection.applied -ne $false) {
    throw "Reviewer rejection is invalid"
}

Write-Output "v0.3 acceptance passed: evidence, source revalidation, validation, checkpoint, role policy, package and audit log verified."
