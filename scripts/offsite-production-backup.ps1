[CmdletBinding()]
param(
    [string]$SshHost = "onec-inspector-prod",
    [string]$RemoteDirectory = "/var/backups/1c-ai-inspector",
    [string]$OutputDirectory = "D:\Backups\1c-ai-inspector",
    [ValidateRange(1, 3650)][int]$KeepDays = 30,
    [string]$BucketName = "onec-ai-inspector-backups",
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$WranglerVersion = "4.110.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$downloadScript = Join-Path $PSScriptRoot "download-production-backups.ps1"
$uploadScript = Join-Path $PSScriptRoot "upload-production-backups-r2.ps1"

& $downloadScript -SshHost $SshHost -RemoteDirectory $RemoteDirectory -OutputDirectory $OutputDirectory -KeepDays $KeepDays
if (-not $?) {
    throw "Production backup download failed"
}

& $uploadScript -InputDirectory $OutputDirectory -BucketName $BucketName -WranglerVersion $WranglerVersion
if (-not $?) {
    throw "R2 backup upload failed"
}

Write-Output "Off-site backup pipeline passed: VPS, local disk and R2 copies verified."
