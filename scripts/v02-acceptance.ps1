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
    if ($projects.Count -lt 1) { throw "No project is available for v0.2 acceptance" }
    $ProjectId = $projects[0].id
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$proposalBody = @{
    projectId = $ProjectId
    title = "v0.2 acceptance $stamp"
    summary = "Proposal-only acceptance flow"
    sourceRevision = "acceptance-$stamp"
    files = @(@{
        path = "CommonModules/AcceptanceSmoke.bsl"
        original = "Procedure AcceptanceSmoke();`nEndProcedure;`n"
        proposed = "Procedure AcceptanceSmoke();`n`tReturn True;`nEndProcedure;`n"
    })
}

$proposal = Post-Api "/api/v1/patch-proposals" $proposalBody
if ($proposal.status -ne "proposed") { throw "Proposal was not created as proposed" }

$impact = Post-Api "/api/v1/patch-proposals/$($proposal.id)/impact"
if ($impact.status -ne "analyzed" -or @($impact.impact).Count -lt 1) {
    throw "Candidate impact was not recorded"
}

$checkpoint = Post-Api "/api/v1/patch-proposals/$($proposal.id)/checkpoint"
if ($checkpoint.status -ne "checkpointed" -or $checkpoint.applied -ne $false -or -not $checkpoint.checkpointRef) {
    throw "Logical checkpoint is invalid"
}

$decision = Post-Api "/api/v1/patch-proposals/$($proposal.id)/approve" @{
    actor = "v02-acceptance"
    note = "Approval is recorded without applying the diff."
}
if ($decision.status -ne "approved" -or $decision.applied -ne $false) {
    throw "Approval workflow is invalid"
}

$events = Get-Api "/api/v1/patch-proposals/$($proposal.id)/events"
$eventTypes = @($events.events | ForEach-Object { $_.type })
$expected = @("created", "impact_analyzed", "checkpointed", "approved")
if ($eventTypes.Count -ne $expected.Count -or (Compare-Object $eventTypes $expected)) {
    throw "Unexpected proposal event log: $($eventTypes -join ', ')"
}

$rejectBody = @{
    projectId = $ProjectId
    title = "v0.2 rejection acceptance $stamp"
    summary = "Proposal-only rejection flow"
    files = @(@{
        path = "CommonModules/RejectionSmoke.bsl"
        original = "A`n"
        proposed = "B`n"
    })
}
$rejectProposal = Post-Api "/api/v1/patch-proposals" $rejectBody
$rejection = Post-Api "/api/v1/patch-proposals/$($rejectProposal.id)/reject" @{
    actor = "v02-acceptance"
    note = "Rejected without applying the diff."
}
if ($rejection.status -ne "rejected" -or $rejection.applied -ne $false) {
    throw "Rejection workflow is invalid"
}

Write-Output "v0.2 Patch Planner acceptance passed: proposal, impact, checkpoint, approve, reject, and audit log verified."
