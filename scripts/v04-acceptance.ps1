param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$AuthToken,
    [string]$OwnerToken,
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

if (-not $AuthToken -or -not $OwnerToken) { throw "AuthToken and OwnerToken are required" }
$authHeaders = @{ Authorization = "Bearer $AuthToken" }
$ownerHeaders = @{ Authorization = "Bearer $OwnerToken" }

$health = Get-Api "/health"
if ($health.status -ne "ok") { throw "Backend health is not ok" }
if (-not $ProjectId) {
    $projects = @(Get-Api "/api/v1/projects")
    if ($projects.Count -lt 1) { throw "No project is available for v0.4 acceptance" }
    $ProjectId = $projects[0].id
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$proposal = Post-Api "/api/v1/patch-proposals" @{
    projectId = $ProjectId
    title = "v0.4 acceptance $stamp"
    summary = "Automatic evidence, signed auth, policy and package verification"
    sourceRevision = "v0.4-acceptance-$stamp"
    files = @(@{ path = "CommonModules/Orders.bsl"; original = "A`n"; proposed = "B`n" })
}

$impact = Post-Api "/api/v1/patch-proposals/$($proposal.id)/impact/mcp"
if ($impact.status -ne "analyzed_mcp" -or @($impact.impact | Where-Object { $_.risk -eq "evidenced" }).Count -lt 1) {
    throw "Automatic MCP evidence was not recorded"
}

$source = Post-Api "/api/v1/patch-proposals/$($proposal.id)/revalidate" @{
    currentRevision = $proposal.sourceRevision
    files = @(@{ path = "CommonModules/Orders.bsl"; current = "A`n" })
}
if ($source.status -ne "valid") { throw "Source revalidation failed" }
if ((Post-Api "/api/v1/patch-proposals/$($proposal.id)/validate").status -ne "valid") { throw "Patch validation failed" }
if ((Post-Api "/api/v1/patch-proposals/$($proposal.id)/checkpoint").status -ne "checkpointed") { throw "Checkpoint failed" }

try {
    Post-Api "/api/v1/patch-proposals/$($proposal.id)/approve" @{ note = "No auth" } | Out-Null
    throw "Unauthenticated approval unexpectedly succeeded"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw }
}

$approved = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/patch-proposals/$($proposal.id)/approve" -Headers $authHeaders -ContentType "application/json" -Body (@{ note = "Maintainer acceptance approval." } | ConvertTo-Json)
if ($approved.status -ne "approved" -or $approved.applied -ne $false) { throw "Maintainer approval failed" }

$packagePath = Join-Path $env:TEMP "one-c-ai-inspector-v04-$PID.zip"
try {
    $download = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/api/v1/patch-proposals/$($proposal.id)/package" -Headers $authHeaders -OutFile $packagePath -PassThru
    if ($download.StatusCode -ne 200 -or $download.Headers["Content-Type"] -notlike "application/zip*") { throw "Signed package download failed" }
    $verified = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/patch-proposals/$($proposal.id)/package/verify" -Headers $authHeaders -ContentType "application/zip" -InFile $packagePath
    if ($verified.valid -ne $true -or $verified.algorithm -ne "HMAC-SHA256") { throw "Package signature verification failed" }
} finally {
    Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue
}

$candidate = Post-Api "/api/v1/patch-proposals" @{
    projectId = $ProjectId
    title = "v0.4 candidate policy $stamp"
    summary = "Owner-only candidate risk policy"
    sourceRevision = "v0.4-candidate-$stamp"
    files = @(@{ path = "CommonModules/Unknown.bsl"; original = "A`n"; proposed = "B`n" })
}
Post-Api "/api/v1/patch-proposals/$($candidate.id)/impact" | Out-Null
Post-Api "/api/v1/patch-proposals/$($candidate.id)/revalidate" @{
    currentRevision = $candidate.sourceRevision
    files = @(@{ path = "CommonModules/Unknown.bsl"; current = "A`n" })
} | Out-Null
Post-Api "/api/v1/patch-proposals/$($candidate.id)/validate" | Out-Null
Post-Api "/api/v1/patch-proposals/$($candidate.id)/checkpoint" | Out-Null
try {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/patch-proposals/$($candidate.id)/approve" -Headers $authHeaders -ContentType "application/json" -Body (@{ note = "Candidate maintainer" } | ConvertTo-Json) -ErrorAction Stop | Out-Null
    throw "Maintainer unexpectedly approved candidate risk"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw }
}
$ownerApproval = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/patch-proposals/$($candidate.id)/approve" -Headers $ownerHeaders -ContentType "application/json" -Body (@{ note = "Owner candidate approval." } | ConvertTo-Json)
if ($ownerApproval.status -ne "approved") { throw "Owner candidate approval failed" }

Write-Output "v0.4 acceptance passed: auth, MCP evidence, revalidation, validation, policy, signed package and verify flow verified."
