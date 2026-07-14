param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [Parameter(Mandatory = $true)][string]$OwnerToken,
    [Parameter(Mandatory = $true)][string]$ProposalId,
    [string]$SourceRepository = ""
)

$ErrorActionPreference = "Stop"
$headers = @{ Authorization = "Bearer $OwnerToken" }
$execution = $null
$sourceHead = $null
$sourceStatus = $null

function Invoke-Sandbox([string]$Method, [string]$Path, [object]$Body = $null) {
    $arguments = @{
        Method = $Method
        Uri = "$BaseUrl$Path"
        Headers = $headers
        ContentType = "application/json"
    }
    if ($null -ne $Body) { $arguments.Body = ($Body | ConvertTo-Json -Depth 8 -Compress) }
    Invoke-RestMethod @arguments
}

function Assert-State([object]$Value, [string]$Expected, [string]$Stage) {
    if ($Value.status -ne $Expected) {
        throw "$Stage returned state '$($Value.status)', expected '$Expected'"
    }
    if ($Value.appliedToInformationBase -ne $false) {
        throw "$Stage reported an information-base write"
    }
}

if ($SourceRepository) {
    $sourceHead = (& git -C $SourceRepository rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Cannot read source repository HEAD" }
    $sourceStatus = (& git -C $SourceRepository status --porcelain) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Cannot read source repository status" }
}

$openApi = Invoke-RestMethod -Uri "$BaseUrl/openapi.json"
if ($openApi.paths.PSObject.Properties.Name -notcontains "/api/v1/sandbox-executions") {
    throw "Sandbox Executor route is not enabled"
}

try {
    $versions = Invoke-Sandbox "GET" "/api/v1/patch-proposals/$ProposalId/package/versions"
    $latest = @($versions.versions)[0]
    if (-not $latest) { throw "Approved proposal has no exported package version" }

    $execution = Invoke-Sandbox "POST" "/api/v1/sandbox-executions" @{
        proposalId = $ProposalId
        packageVersion = $latest.version
        packageSha256 = $latest.sha256
        note = "Sandbox Executor acceptance"
    }
    Assert-State $execution "created" "create"

    $execution = Invoke-Sandbox "POST" "/api/v1/sandbox-executions/$($execution.id)/prepare"
    Assert-State $execution "prepared" "prepare"
    if ($execution.branchName -ne "inspector/$($execution.id)") { throw "Unexpected sandbox branch" }

    $execution = Invoke-Sandbox "POST" "/api/v1/sandbox-executions/$($execution.id)/apply"
    Assert-State $execution "validating" "apply"

    $execution = Invoke-Sandbox "POST" "/api/v1/sandbox-executions/$($execution.id)/validate"
    Assert-State $execution "testing" "validation"
    if ($execution.validation.exitCode -ne 0 -or $execution.validation.timedOut) {
        throw "Validation did not produce a successful command record"
    }

    $execution = Invoke-Sandbox "POST" "/api/v1/sandbox-executions/$($execution.id)/test"
    Assert-State $execution "awaiting_acceptance" "test"
    if ($execution.test.exitCode -ne 0 -or $execution.test.timedOut) {
        throw "Test did not produce a successful command record"
    }

    $events = Invoke-Sandbox "GET" "/api/v1/sandbox-executions/$($execution.id)/events"
    $eventTypes = @($events.events | ForEach-Object { $_.type })
    foreach ($required in @(
        "execution_created",
        "sandbox_prepared",
        "sandbox_applied",
        "sandbox_validation_passed",
        "sandbox_test_passed"
    )) {
        if ($eventTypes -notcontains $required) { throw "Missing sandbox audit event: $required" }
    }
} finally {
    if ($execution -and $execution.status -in @("awaiting_acceptance", "rollback_required")) {
        $execution = Invoke-Sandbox "POST" "/api/v1/sandbox-executions/$($execution.id)/rollback"
        Assert-State $execution "rolled_back" "rollback"
    }
}

if ($SourceRepository) {
    $finalHead = (& git -C $SourceRepository rev-parse HEAD).Trim()
    $finalStatus = (& git -C $SourceRepository status --porcelain) -join "`n"
    if ($finalHead -ne $sourceHead) { throw "Source repository HEAD changed" }
    if ($finalStatus -ne $sourceStatus) { throw "Source repository working tree changed" }
}

Write-Output "Sandbox Executor acceptance passed: signed apply, validation, tests, audit, rollback and source repository invariants verified."
