param(
    [switch]$KeepRunning,
    [string]$ProductionEnvFile
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$backupDirectory = Join-Path $env:TEMP ("one-c-ai-inspector-release-backup-" + $PID)

function Invoke-WithRetry([string]$Name, [scriptblock]$Action, [int]$Attempts = 3) {
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            & $Action
            return
        } catch {
            if ($attempt -eq $Attempts) { throw }
            Write-Warning "$Name failed on attempt $attempt/$Attempts; retrying in 5 seconds."
            Start-Sleep -Seconds 5
        }
    }
}

Push-Location $repo
try {
    .\scripts\keycloak-acceptance.ps1 -KeepRunning
    Invoke-WithRetry "EDT live acceptance" { .\scripts\edt-live-acceptance.ps1 }
    .\scripts\security-load-acceptance.ps1 -Count 20
    .\scripts\backup.ps1 -OutputDirectory $backupDirectory
    if ($ProductionEnvFile) {
        .\scripts\production-preflight.ps1 -EnvFile $ProductionEnvFile -WithKeycloak -WithEdge
    } else {
        Write-Output "Production preflight skipped: pass -ProductionEnvFile with real DNS and secret values to run it."
    }
    Write-Output "Release acceptance passed: Keycloak JWT, EDT MCP, security/load and PostgreSQL backup verified."
} finally {
    if (Test-Path -LiteralPath $backupDirectory) {
        Remove-Item -LiteralPath $backupDirectory -Recurse -Force
    }
    if (-not $KeepRunning) {
        docker compose --env-file .env -f docker-compose.yml -f docker-compose.keycloak.yml down | Out-Null
    }
    Pop-Location
}
