param(
    [string]$BaseUrl = "https://inspector.michael.kz",
    [Parameter(Mandatory = $true)][string]$CodeTaskId,
    [Parameter(Mandatory = $true)][string]$QueryTaskId,
    [Parameter(Mandatory = $true)][string]$AuditTaskId,
    [ValidateRange(1, 200)][int]$LoadCount = 20
)

$ErrorActionPreference = "Stop"

function Invoke-Stage([string]$Name, [string]$ScriptName, [hashtable]$Parameters) {
    $scriptPath = Join-Path $PSScriptRoot $ScriptName
    try {
        & $scriptPath @Parameters
        if (-not $?) { throw "stage returned a failure status" }
    } catch {
        throw "Final production acceptance stage '$Name' failed: $($_.Exception.Message)"
    }
}

Invoke-Stage "production monitor" "production-monitor.ps1" @{ BaseUrl = $BaseUrl }
Invoke-Stage "error contract" "error-contract-acceptance.ps1" @{
    BaseUrl = $BaseUrl
    CompletedTaskId = $CodeTaskId
}
Invoke-Stage "v0.7 UAT" "v07-uat.ps1" @{
    BaseUrl = $BaseUrl
    CodeTaskId = $CodeTaskId
    QueryTaskId = $QueryTaskId
    AuditTaskId = $AuditTaskId
}
Invoke-Stage "security and load" "security-load-acceptance.ps1" @{
    BaseUrl = $BaseUrl
    Count = $LoadCount
}

Write-Output "Final production acceptance passed: monitor, error contract, three read-only agents and security/load checks verified."
