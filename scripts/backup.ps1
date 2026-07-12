param(
    [string]$EnvFile = ".env",
    [string]$OutputDirectory = ".\backups",
    [ValidateRange(1, 3650)][int]$KeepDays = 14
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
$container = $null
$tempName = "/tmp/one-c-ai-inspector-backup-$PID.dump"
try {
    $outputPath = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = Join-Path $outputPath "inspector-$timestamp.dump"
    $container = (& docker compose --env-file $EnvFile ps -q postgres).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $container) { throw "PostgreSQL container is not running" }

    $dumpCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" > ' + $tempName
    & docker exec $container sh -c $dumpCommand | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
    & docker cp "${container}:$tempName" $backupPath | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $backupPath)) { throw "Backup copy failed" }

    & docker exec $container pg_restore --list $tempName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Backup verification failed" }
    Get-ChildItem -LiteralPath $outputPath -Filter "*.dump" -File |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
    if ((Get-Item -LiteralPath $backupPath).Length -le 0) { throw "Backup is empty" }
    Write-Output "PostgreSQL backup created and verified: $backupPath"
} finally {
    if ($container) { & docker exec $container rm -f $tempName | Out-Null }
    Pop-Location
}
