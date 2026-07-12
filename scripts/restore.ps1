param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [string]$EnvFile = ".env",
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) { throw "Restore is destructive; rerun with -ConfirmRestore after checking the backup file." }

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
$container = $null
$tempName = "/tmp/one-c-ai-inspector-restore-$PID.dump"
try {
    $resolvedBackup = (Resolve-Path -LiteralPath $BackupFile -ErrorAction Stop).Path
    if ((Get-Item -LiteralPath $resolvedBackup).Length -le 0) { throw "Backup file is empty" }
    $container = (& docker compose --env-file $EnvFile ps -q postgres).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $container) { throw "PostgreSQL container is not running" }
    & docker cp $resolvedBackup "${container}:$tempName" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Backup copy to PostgreSQL container failed" }
    $restoreCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" ' + $tempName
    & docker exec $container sh -c $restoreCommand | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }
    Write-Output "PostgreSQL restore completed from $resolvedBackup"
} finally {
    if ($container) { & docker exec $container rm -f $tempName | Out-Null }
    Pop-Location
}
