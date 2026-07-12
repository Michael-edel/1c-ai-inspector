param([switch]$KeepRunning)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

function Test-DockerEngine([int]$TimeoutMs) {
    $stdout = Join-Path $env:TEMP "one-c-ai-inspector-docker-$PID.out"
    $stderr = Join-Path $env:TEMP "one-c-ai-inspector-docker-$PID.err"
    $process = Start-Process -FilePath "docker" -ArgumentList "info" -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    try {
        if (-not $process.WaitForExit($TimeoutMs)) {
            $process.Kill()
            throw "Docker command timed out after ${TimeoutMs}ms"
        }
        if ($process.ExitCode -ne 0) {
            throw ((Get-Content -LiteralPath $stderr -Raw).Trim())
        }
    } finally {
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
}
$envPath = Join-Path $repo ".env"

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Missing .env. Copy .env.example to .env and set real MCP/Model values."
}

$values = @{}
Get-Content -LiteralPath $envPath | ForEach-Object {
    if ($_ -match "^\s*([^#=][^=]*)=(.*)$") {
        $values[$matches[1].Trim()] = $matches[2].Trim()
    }
}

 $missing = @()
foreach ($key in @("MCP_SERVER_URL", "MODEL_API_URL", "MODEL_API_KEY")) {
    if (-not $values[$key] -or $values[$key] -like "replace-with-*") {
        $missing += $key
    }
}
if ($missing.Count -gt 0) {
    throw "Not configured in .env: $($missing -join ', ')"
}

try { Test-DockerEngine 15000 }
catch { throw "Docker Engine is unavailable or unresponsive: $($_.Exception.Message)" }

Push-Location $repo
try {
    docker compose --env-file .env up --build -d
    try {
        $deadline = (Get-Date).AddMinutes(2)
        do {
            try {
                $health = Invoke-RestMethod http://127.0.0.1:8000/health
                if ($health.status -eq "ok") { break }
            } catch { Start-Sleep -Seconds 3 }
        } while ((Get-Date) -lt $deadline)
        if (-not $health -or $health.status -ne "ok") { throw "Backend healthcheck timed out" }

        $diagnostics = Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/diagnostics
        if (-not $diagnostics.model.apiKeyConfigured) { throw "Model API key is not configured" }
        Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/mcp/health | Out-Null
        Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/mcp/tools | Out-Null
        if ($values["MCP_PROJECTS_TOOL"]) {
            Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/projects/sync | Out-Null
        }
        Write-Output "Live acceptance preflight passed"
    } finally {
        if (-not $KeepRunning) { docker compose --env-file .env down }
    }
} finally {
    Pop-Location
}
