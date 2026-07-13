param(
    [string]$BaseUrl = "https://inspector.michael.kz",
    [Parameter(Mandatory = $true)][string]$CompletedTaskId
)

$ErrorActionPreference = "Stop"

function Assert-Status([string]$Method, [string]$Path, [int]$ExpectedStatus) {
    try {
        Invoke-RestMethod -Method $Method -Uri "$BaseUrl$Path" | Out-Null
        throw "Expected HTTP $ExpectedStatus for $Method $Path"
    } catch {
        if (-not $_.Exception.Response) { throw }
        $actual = [int]$_.Exception.Response.StatusCode
        if ($actual -ne $ExpectedStatus) { throw "Unexpected HTTP status for $Method ${Path}: $actual" }
    }
}

Assert-Status "GET" "/api/v1/tasks/tsk_missing_for_error_contract" 404
Assert-Status "GET" "/api/v1/tasks/tsk_missing_for_error_contract/report" 404

$terminalCancelSucceeded = $false
try {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/tasks/$CompletedTaskId/cancel" | Out-Null
    $terminalCancelSucceeded = $true
} catch {
    $response = $_.Exception.Response
    if (-not $response) { throw }
    if ([int]$response.StatusCode -ne 409) { throw "Unexpected terminal cancel status: $([int]$response.StatusCode)" }
    $body = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($body.detail.code -ne "TASK_NOT_CANCELLABLE") { throw "Unexpected terminal cancel code" }
}
if ($terminalCancelSucceeded) { throw "Expected terminal task cancellation to be rejected" }

$metricsSucceeded = $false
try {
    Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/metrics" | Out-Null
    $metricsSucceeded = $true
} catch {
    if (-not $_.Exception.Response) { throw }
    if ([int]$_.Exception.Response.StatusCode -ne 401) { throw }
}
if ($metricsSucceeded) { throw "Unauthenticated metrics request unexpectedly succeeded" }

$history = Invoke-RestMethod -Uri "$BaseUrl/api/v1/tasks"
foreach ($item in $history) {
    foreach ($forbiddenProperty in @("request", "requestJson", "result", "resultJson")) {
        if ($item.PSObject.Properties.Name -contains $forbiddenProperty) { throw "Task history exposes forbidden property" }
    }
}

Write-Output "Error contract acceptance passed: missing tasks, terminal cancellation, metrics auth and safe task history verified."
