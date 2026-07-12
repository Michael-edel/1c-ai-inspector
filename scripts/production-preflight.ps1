param([string]$EnvFile = ".env", [switch]$WithKeycloak, [switch]$WithEdge)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $resolvedEnv = (Resolve-Path -LiteralPath $EnvFile -ErrorAction Stop).Path
    $values = @{}
    Get-Content -LiteralPath $resolvedEnv | ForEach-Object {
        if ($_ -match "^\s*([^#=][^=]*)=(.*)$") { $values[$matches[1].Trim()] = $matches[2].Trim() }
    }

    foreach ($key in @("MCP_SERVER_URL", "MODEL_API_URL", "MODEL_API_KEY", "AUTH_JWKS_URL", "AUTH_ISSUER", "AUTH_AUDIENCE", "INSPECTOR_PACKAGE_SIGNING_SECRET")) {
        if (-not $values[$key] -or $values[$key] -like "replace-with-*") { throw "Not configured in production env: $key" }
    }
    if ($values["INSPECTOR_AUTH_MODE"] -ne "jwks") { throw "INSPECTOR_AUTH_MODE must be jwks for production" }
    if ($values["INSPECTOR_PACKAGE_SIGNING_SECRET"].Length -lt 32) { throw "INSPECTOR_PACKAGE_SIGNING_SECRET must be at least 32 characters" }

    $composeFiles = @("-f", "docker-compose.yml", "-f", "docker-compose.production.yml")
    if ($WithEdge -and -not $WithKeycloak) { throw "WithEdge requires WithKeycloak" }
    if ($WithKeycloak) {
        foreach ($key in @("KEYCLOAK_PUBLIC_URL", "KEYCLOAK_DB_NAME", "KEYCLOAK_DB_USER", "KEYCLOAK_DB_PASSWORD", "KEYCLOAK_ADMIN_USERNAME", "KEYCLOAK_ADMIN_PASSWORD")) {
            if (-not $values[$key] -or $values[$key] -like "replace-with-*") { throw "Not configured in production env: $key" }
        }
        if ($values["KEYCLOAK_PUBLIC_URL"] -notlike "https://*") { throw "KEYCLOAK_PUBLIC_URL must use https" }
        if ($values["KEYCLOAK_DB_PASSWORD"].Length -lt 24 -or $values["KEYCLOAK_ADMIN_PASSWORD"].Length -lt 24) {
            throw "Keycloak DB and admin passwords must be at least 24 characters"
        }
        $composeFiles += @("-f", "docker-compose.keycloak.production.yml")
    }
    if ($WithEdge) {
        foreach ($key in @("APP_DOMAIN", "IDP_DOMAIN")) {
            if (-not $values[$key] -or $values[$key] -like "replace-with-*") { throw "Not configured in production env: $key" }
            if ($values[$key] -match "localhost|127\.0\.0\.1|example\.com") { throw "$key must be a real DNS name" }
        }
        if ($values["APP_DOMAIN"] -eq $values["IDP_DOMAIN"]) { throw "APP_DOMAIN and IDP_DOMAIN must be different" }
        $composeFiles += @("-f", "docker-compose.edge.production.yml")
    }

    $config = & docker compose --env-file $resolvedEnv @composeFiles config 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Production Compose config failed" }
    if ($config -match "published: 5432") { throw "PostgreSQL must not be published in production Compose" }
    if ($WithEdge -and ($config -match "published: 8000" -or $config -match "published: 5173")) {
        throw "Backend and frontend ports must stay internal when edge proxy is enabled"
    }
    $scope = if ($WithEdge) { "application, persistent Keycloak and edge TLS" } elseif ($WithKeycloak) { "application and persistent Keycloak" } else { "application" }
    Write-Output "Production preflight passed: $scope secrets, Compose override and closed PostgreSQL port verified."
} finally {
    Pop-Location
}
