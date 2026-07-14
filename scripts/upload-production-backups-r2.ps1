[CmdletBinding()]
param(
    [string]$InputDirectory = "D:\Backups\1c-ai-inspector",
    [string]$BucketName = "onec-ai-inspector-backups",
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$WranglerVersion = "4.110.0",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$inputRoot = [System.IO.Path]::GetFullPath($InputDirectory)
$successPath = Join-Path $inputRoot "last-success.json"
if (-not (Test-Path -LiteralPath $successPath -PathType Leaf)) {
    throw "Verified local backup manifest is missing: $successPath"
}

$localRecord = Get-Content -Raw -LiteralPath $successPath | ConvertFrom-Json
$manifestFiles = @($localRecord.files)
if ($manifestFiles.Count -ne 2) {
    throw "Expected exactly two verified dumps in last-success.json"
}

$verifiedFiles = foreach ($entry in $manifestFiles) {
    $name = [string]$entry.Name
    $expectedHash = ([string]$entry.Sha256).ToLowerInvariant()
    if ($name -notmatch '^inspector-(postgres|keycloak)-(?<year>\d{4})(?<month>\d{2})\d{2}T\d{6}Z\.dump$') {
        throw "Unexpected backup filename in manifest: $name"
    }
    $year = $Matches.year
    $month = $Matches.month
    if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid SHA-256 in manifest for $name"
    }

    $path = Join-Path $inputRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Backup from manifest is missing: $path"
    }

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Local SHA-256 mismatch for $name"
    }

    [pscustomobject]@{
        Name = $name
        Path = $path
        Sha256 = $actualHash
        Bytes = (Get-Item -LiteralPath $path).Length
        ObjectKey = "production/$year/$month/$name"
    }
}

if ($ValidateOnly) {
    Write-Output "R2 preflight passed: $($verifiedFiles.Count) local dumps match last-success.json."
    return
}

$npx = (Get-Command npx.cmd -ErrorAction Stop).Source
function Invoke-Wrangler {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & $npx -y "wrangler@$WranglerVersion" @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Wrangler failed with exit code $LASTEXITCODE"
    }
    if ($output) {
        Write-Host ($output -join [Environment]::NewLine)
    }
}

$verificationRoot = Join-Path ([System.IO.Path]::GetTempPath()) "1c-ai-inspector-r2-$PID"
New-Item -ItemType Directory -Force -Path $verificationRoot | Out-Null

try {
    $uploaded = foreach ($file in $verifiedFiles) {
        $remoteObject = "$BucketName/$($file.ObjectKey)"
        Invoke-Wrangler @(
            "r2", "object", "put", $remoteObject,
            "--file", $file.Path,
            "--content-type", "application/octet-stream",
            "--remote"
        )

        $downloadedPath = Join-Path $verificationRoot $file.Name
        Invoke-Wrangler @(
            "r2", "object", "get", $remoteObject,
            "--file", $downloadedPath,
            "--remote"
        )

        $downloadedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $downloadedPath).Hash.ToLowerInvariant()
        if ($downloadedHash -ne $file.Sha256) {
            throw "R2 verification SHA-256 mismatch for $($file.Name)"
        }

        [pscustomobject]@{
            Name = $file.Name
            ObjectKey = $file.ObjectKey
            Sha256 = $file.Sha256
            Bytes = $file.Bytes
        }
    }

    $r2Record = [ordered]@{
        completedAt = (Get-Date).ToUniversalTime().ToString("o")
        bucket = $BucketName
        wranglerVersion = $WranglerVersion
        files = @($uploaded)
    }
    $r2Record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $inputRoot "r2-last-success.json") -Encoding utf8

    Write-Output "R2 backup passed: $($uploaded.Count) objects uploaded and downloaded with matching SHA-256."
}
finally {
    if (Test-Path -LiteralPath $verificationRoot) {
        Remove-Item -LiteralPath $verificationRoot -Recurse -Force
    }
}
