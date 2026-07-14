param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [Parameter(Mandatory = $true)][string]$OwnerToken,
    [Parameter(Mandatory = $true)][string]$TaskId,
    [Parameter(Mandatory = $true)][string]$FindingId,
    [Parameter(Mandatory = $true)][string]$GitCommit,
    [string]$GitPath = "CommonModules/AcceptanceSmoke.bsl",
    [string]$Proposed = "Procedure AcceptanceSmoke();`n`tReturn True;`nEndProcedure;`n"
)

$ErrorActionPreference = "Stop"
$headers = @{ Authorization = "Bearer $OwnerToken" }

function Get-Api([string]$Path, [hashtable]$Headers = @{}) {
    Invoke-RestMethod -Uri "$BaseUrl$Path" -Headers $Headers
}

function Post-Api([string]$Path, [object]$Body = $null, [hashtable]$Headers = @{}) {
    $params = @{ Method = "Post"; Uri = "$BaseUrl$Path"; Headers = $Headers }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body | ConvertTo-Json -Depth 10
    }
    Invoke-RestMethod @params
}

if ($GitCommit -notmatch "^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$") {
    throw "GitCommit must be a full 40/64-character commit SHA"
}
if ((Get-Api "/health").status -ne "ok") { throw "Backend health is not ok" }

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$proposal = Post-Api "/api/v1/patch-proposals/from-finding" @{
    taskId = $TaskId
    findingId = $FindingId
    title = "v0.2 report-to-patch acceptance $stamp"
    summary = "Persisted source, Git checkpoint and manual handoff"
    path = $GitPath
    proposed = $Proposed
    sourceRevision = $GitCommit
} $headers
if ($proposal.status -ne "proposed" -or $proposal.taskId -ne $TaskId) {
    throw "Proposal was not linked to the completed task"
}

$impact = Post-Api "/api/v1/patch-proposals/$($proposal.id)/impact"
if ($impact.status -ne "analyzed" -or @($impact.impact).Count -lt 1) {
    throw "Candidate impact was not recorded"
}
if ((Post-Api "/api/v1/patch-proposals/$($proposal.id)/revalidate/from-task" $null $headers).status -ne "valid") {
    throw "Persisted source revalidation failed"
}
if ((Post-Api "/api/v1/patch-proposals/$($proposal.id)/validate").status -ne "valid") {
    throw "Patch validation failed"
}

$checkpoint = Post-Api "/api/v1/patch-proposals/$($proposal.id)/checkpoint/git" $null $headers
if ($checkpoint.status -ne "checkpointed" -or $checkpoint.commitSha -ne $GitCommit -or $checkpoint.applied -ne $false) {
    throw "Immutable Git checkpoint failed"
}
$approved = Post-Api "/api/v1/patch-proposals/$($proposal.id)/approve" @{
    note = "Owner approved candidate impact for manual handoff."
} $headers
if ($approved.status -ne "approved" -or $approved.applied -ne $false) {
    throw "Owner approval failed"
}

$packagePath = Join-Path $env:TEMP "one-c-ai-inspector-v02-$PID.zip"
try {
    $download = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/api/v1/patch-proposals/$($proposal.id)/package" -Headers $headers -OutFile $packagePath -PassThru
    $version = [int]@($download.Headers["X-Package-Version"])[0]
    $packageSha = [string]@($download.Headers["X-Package-Sha256"])[0]
    if ($version -lt 1 -or $packageSha -notmatch "^[0-9a-f]{64}$") {
        throw "Signed package metadata is invalid"
    }
    $verified = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/patch-proposals/$($proposal.id)/package/verify" -Headers $headers -ContentType "application/zip" -InFile $packagePath
    if ($verified.valid -ne $true -or $verified.status -ne "approved") {
        throw "Signed package verification failed"
    }
    $handoff = Post-Api "/api/v1/patch-proposals/$($proposal.id)/handoff" @{
        packageVersion = $version
        packageSha256 = $packageSha
        targetEnvironment = $proposal.targetEnvironment
        note = "Package transferred to the manual operator acceptance queue."
    } $headers
    if ($handoff.applied -ne $false -or $handoff.applyAllowed -ne $false -or -not $handoff.handoffId) {
        throw "Manual handoff contract is invalid"
    }
} finally {
    Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue
}

$events = Get-Api "/api/v1/patch-proposals/$($proposal.id)/events"
$eventTypes = @($events.events | ForEach-Object { $_.type })
$expected = @(
    "created",
    "source_imported",
    "impact_analyzed",
    "source_revalidated",
    "validated",
    "git_checkpointed",
    "approved",
    "package_stored",
    "package_exported",
    "manual_handoff_created"
)
foreach ($eventType in $expected) {
    if ($eventTypes -notcontains $eventType) { throw "Missing proposal event: $eventType" }
}

$openApi = Get-Api "/openapi.json"
if ($openApi.paths.PSObject.Properties.Name -match "/apply(?:/|$)") {
    throw "Apply endpoint must not exist in v0.2"
}

Write-Output "v0.2 acceptance passed: persisted source, Git checkpoint, approval, signed package, manual handoff and no-apply boundary verified."
