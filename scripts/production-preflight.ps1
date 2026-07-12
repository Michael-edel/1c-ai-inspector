param([string]$EnvFile = ".env")

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

    $config = & docker compose --env-file $resolvedEnv -f docker-compose.yml -f docker-compose.production.yml config 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Production Compose config failed" }
    if ($config -match "5432:5432") { throw "PostgreSQL must not be published in production Compose" }
    Write-Output "Production preflight passed: JWKS auth, package signing secret, Compose override and closed PostgreSQL port verified."
} finally {
    Pop-Location
}
