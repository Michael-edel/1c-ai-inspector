param([switch]$Production)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $envValues = @{}
    if (Test-Path -LiteralPath ".env") {
        Get-Content -LiteralPath ".env" | ForEach-Object {
            if ($_ -match "^\s*([^#=][^=]*)=(.*)$") { $envValues[$matches[1].Trim()] = $matches[2].Trim() }
        }
    }
    $mode = if ($envValues["INSPECTOR_AUTH_MODE"]) { $envValues["INSPECTOR_AUTH_MODE"] } else { "signed" }
    if ($Production) {
        .\scripts\production-preflight.ps1 -EnvFile ".env"
        .\scripts\idp-jwks-acceptance.ps1
        docker compose --env-file .env -f docker-compose.yml -f docker-compose.production.yml config --quiet
    } elseif ($mode -eq "jwks") {
        .\scripts\idp-jwks-acceptance.ps1
    } else {
        Write-Output "Local signed auth mode detected; external IdP smoke is reserved for -Production."
    }
    .\scripts\edt-live-acceptance.ps1
    .\scripts\security-load-acceptance.ps1 -Count 20
    docker compose --env-file .env.example config --quiet
    $scope = if ($Production) { "production and local" } else { "local" }
    Write-Output "v0.6 acceptance passed: release version, $scope auth contour, EDT MCP and security/load smoke verified."
} finally {
    Pop-Location
}
