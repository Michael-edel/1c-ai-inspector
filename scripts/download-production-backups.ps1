[CmdletBinding()]
param(
    [string]$SshHost = "onec-inspector-prod",
    [string]$RemoteDirectory = "/var/backups/1c-ai-inspector",
    [string]$OutputDirectory = "D:\Backups\1c-ai-inspector",
    [ValidateRange(1, 3650)][int]$KeepDays = 30
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Quote-ShellArgument {
    param([Parameter(Mandatory)][string]$Value)
    $singleQuote = [string][char]39
    $doubleQuote = [string][char]34
    $escapedQuote = $singleQuote + $doubleQuote + $singleQuote + $doubleQuote + $singleQuote
    return $singleQuote + $Value.Replace($singleQuote, $escapedQuote) + $singleQuote
}

function Invoke-Ssh {
    param([Parameter(Mandatory)][string]$Command)
    $output = & ssh -o BatchMode=yes -o ConnectTimeout=15 $SshHost $Command
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed with exit code $LASTEXITCODE"
    }
    return @($output)
}

$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$quotedRemoteDirectory = Quote-ShellArgument $RemoteDirectory
$metadataCommand = @"
set -euo pipefail
for prefix in inspector-postgres inspector-keycloak; do
  path=`$(sudo find $quotedRemoteDirectory -maxdepth 1 -type f -name "`${prefix}-*.dump" -printf '%T@ %p\n' | sort -nr | sed -n '1s/^[^ ]* //p')
  test -n "`$path"
  name=`$(basename "`$path")
  hash=`$(sudo sha256sum "`$path" | awk '{print `$1}')
  printf '%s\t%s\t%s\n' "`$name" "`$hash" "`$path"
done
"@

$metadata = Invoke-Ssh $metadataCommand
if ($metadata.Count -ne 2) {
    throw "Expected metadata for two production dumps, received $($metadata.Count)"
}

$downloaded = foreach ($line in $metadata) {
    $parts = $line -split "`t", 3
    if ($parts.Count -ne 3) {
        throw "Invalid backup metadata returned by server"
    }

    $name, $expectedHash, $remotePath = $parts
    if ($name -notmatch '^inspector-(postgres|keycloak)-\d{8}T\d{6}Z\.dump$') {
        throw "Unexpected backup filename: $name"
    }
    if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid SHA-256 for $name"
    }
    if (-not $remotePath.StartsWith("$($RemoteDirectory.TrimEnd('/'))/", [System.StringComparison]::Ordinal)) {
        throw "Backup path is outside the configured remote directory"
    }

    $destination = Join-Path $outputRoot $name
    $temporary = "$destination.tmp"
    $remoteStaging = "/tmp/1c-ai-inspector-offsite-$PID-$name"
    $stageCommand = "set -e; sudo install -o inspector-admin -g inspector-admin -m 600 " +
        (Quote-ShellArgument $remotePath) + " " + (Quote-ShellArgument $remoteStaging)

    Invoke-Ssh $stageCommand | Out-Null
    try {
        & scp -q -o BatchMode=yes -o ConnectTimeout=15 "${SshHost}:$remoteStaging" $temporary
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temporary)) {
            throw "SCP download failed for $name"
        }

        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "SHA-256 mismatch for $name"
        }

        Move-Item -Force -LiteralPath $temporary -Destination $destination
        [pscustomobject]@{
            Name = $name
            Sha256 = $actualHash
            Bytes = (Get-Item -LiteralPath $destination).Length
        }
    }
    finally {
        Invoke-Ssh ("rm -f " + (Quote-ShellArgument $remoteStaging)) | Out-Null
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -Force -LiteralPath $temporary
        }
    }
}

$cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem -LiteralPath $outputRoot -File -Filter "inspector-*.dump" |
    Where-Object { $_.LastWriteTime -lt $cutoff -and $_.Name -match '^inspector-(postgres|keycloak)-\d{8}T\d{6}Z\.dump$' } |
    Remove-Item -Force

$successRecord = [ordered]@{
    completedAt = (Get-Date).ToUniversalTime().ToString("o")
    source = $SshHost
    files = @($downloaded)
}
$successRecord | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $outputRoot "last-success.json") -Encoding utf8

Write-Output "Off-site backup passed: $($downloaded.Count) verified dumps saved to $outputRoot."
