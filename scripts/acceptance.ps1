param([switch]$SkipDockerRuntime)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Push-Location $repo
try {
    python -m pytest backend/tests -q
    python -m compileall -q backend/app backend/migrations backend/tests
    Push-Location frontend
    try { npm run build } finally { Pop-Location }

    $services = @(docker compose --env-file .env.example config --services)
    if ($LASTEXITCODE -ne 0) { throw "docker compose config failed" }
    $forbidden = @("redis", "celery", "rq", "kubernetes", "api-gateway")
    $unexpected = $services | Where-Object { $forbidden -contains $_ }
    if ($unexpected) { throw "Forbidden v0.1 services found: $($unexpected -join ', ')" }

    if (-not $SkipDockerRuntime) {
        docker info | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Docker Engine is unavailable; rerun with -SkipDockerRuntime only for static checks" }
        docker compose --env-file .env.example up --build -d
        try {
            Invoke-RestMethod http://localhost:8000/health
        } finally {
            docker compose --env-file .env.example down
        }
    }
} finally {
    Pop-Location
}
