[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BridgeEnvFile,
    [string]$SshHost = "onec-inspector-prod",
    [string]$ProductionDirectory = "/opt/1c-ai-inspector",
    [string]$BridgeTaskName = "SalesAiManager-1C-MCP-Bridge",
    [string]$LocalBridgeUrl = "http://127.0.0.1:8091",
    [string]$ExternalBridgeUrl = "https://onec-mcp.michael.kz",
    [string]$InspectorUrl = "https://inspector.michael.kz",
    [string]$CredentialsFile = "D:\пароль.txt",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function New-BridgeToken {
    $bytes = [byte[]]::new(48)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Read-BridgeToken {
    param([Parameter(Mandatory)][string]$Path)

    $content = Get-Content -Raw -LiteralPath $Path
    $match = [regex]::Match($content, '(?m)^ONEC_MCP_INSPECTOR_TOKEN=(?<value>[^\r\n]+)$')
    if (-not $match.Success) {
        throw "ONEC_MCP_INSPECTOR_TOKEN is missing from bridge env file"
    }

    $value = $match.Groups['value'].Value.Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ($value.Length -lt 16) {
        throw "Existing bridge token is unexpectedly short"
    }
    return $value
}

function Write-BridgeToken {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Token
    )

    $content = Get-Content -Raw -LiteralPath $Path
    $updated = [regex]::Replace(
        $content,
        '(?m)^ONEC_MCP_INSPECTOR_TOKEN=[^\r\n]+$',
        "ONEC_MCP_INSPECTOR_TOKEN=$Token"
    )
    if ($updated -eq $content) {
        throw "Bridge token line was not updated"
    }
    Set-Content -LiteralPath $Path -Value $updated -Encoding utf8NoBOM -NoNewline
}

function Set-RemoteBridgeToken {
    param([Parameter(Mandatory)][string]$Token)

    $remoteCommand = @'
set -euo pipefail
IFS= read -r new_token
test "${#new_token}" -ge 32
production_dir="__PRODUCTION_DIRECTORY__"
env_file="$production_dir/.env"
backup_dir="/var/backups/1c-ai-inspector"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
token_file=$(sudo mktemp)
env_tmp=$(sudo mktemp)
cleanup() {
  sudo rm -f "$token_file" "$env_tmp"
}
trap cleanup EXIT
printf '%s' "$new_token" | sudo tee "$token_file" >/dev/null
sudo chmod 600 "$token_file"
sudo install -d -o root -g root -m 700 "$backup_dir"
sudo install -o root -g root -m 600 "$env_file" "$backup_dir/env-pre-bridge-rotation-$timestamp"
sudo python3 - "$env_file" "$token_file" "$env_tmp" <<'PY'
from pathlib import Path
import sys

env_path, token_path, output_path = map(Path, sys.argv[1:])
token = token_path.read_text(encoding="utf-8").strip()
lines = env_path.read_text(encoding="utf-8").splitlines()
matches = [index for index, line in enumerate(lines) if line.startswith("MCP_BRIDGE_TOKEN=")]
if len(matches) != 1:
    raise SystemExit("expected exactly one MCP_BRIDGE_TOKEN entry")
lines[matches[0]] = f"MCP_BRIDGE_TOKEN={token}"
Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
sudo install -o root -g root -m 600 "$env_tmp" "$env_file"
cd "$production_dir"
sudo docker compose --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  -f docker-compose.keycloak.production.yml \
  -f docker-compose.edge.production.yml \
  up -d --no-deps --force-recreate backend worker >/dev/null
'@
    $remoteCommand = $remoteCommand.Replace('__PRODUCTION_DIRECTORY__', $ProductionDirectory)
    $output = $Token | & ssh -o BatchMode=yes -o ConnectTimeout=15 $SshHost $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Remote bridge token update failed with exit code $LASTEXITCODE"
    }
    if ($output) {
        Write-Host ($output -join [Environment]::NewLine)
    }
}

function Restart-BridgeTask {
    Stop-ScheduledTask -TaskName $BridgeTaskName -ErrorAction SilentlyContinue
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ((Get-ScheduledTask -TaskName $BridgeTaskName).State -ne 'Running') {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    Start-ScheduledTask -TaskName $BridgeTaskName
}

function Wait-AuthorizedHealth {
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][string]$Token,
        [ValidateRange(1, 300)][int]$MaxAttempts = 30
    )

    $headers = @{ Authorization = "Bearer $Token" }
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri "$($BaseUrl.TrimEnd('/'))/health" -Headers $headers -TimeoutSec 10
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            if ($attempt -eq $MaxAttempts) {
                throw
            }
        }
        Start-Sleep -Seconds 1
    }
    throw "Authorized bridge health did not become ready: $BaseUrl"
}

function Assert-TokenRejected {
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][string]$Token
    )

    $request = @{
        Uri = "$($BaseUrl.TrimEnd('/'))/health"
        Headers = @{ Authorization = "Bearer $Token" }
        SkipHttpErrorCheck = $true
        TimeoutSec = 15
    }
    $response = Invoke-WebRequest @request
    if ($response.StatusCode -notin @(401, 403)) {
        throw "Retired bridge token was not rejected by $BaseUrl"
    }
}

function Save-CredentialRecord {
    param([Parameter(Mandatory)][string]$Token)

    $parent = Split-Path -Parent $CredentialsFile
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (-not (Test-Path -LiteralPath $CredentialsFile)) {
        New-Item -ItemType File -Path $CredentialsFile | Out-Null
    }

    $currentUserSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $administratorsSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    $acl = [System.Security.AccessControl.FileSecurity]::new()
    $acl.SetOwner($currentUserSid)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($currentUserSid, $systemSid, $administratorsSid)) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $CredentialsFile -AclObject $acl

    $record = @"

[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))] 1C AI Inspector development token rotation
ONEC_MCP_INSPECTOR_TOKEN=$Token
"@
    Add-Content -LiteralPath $CredentialsFile -Value $record -Encoding utf8
}

if (-not (Test-Path -LiteralPath $BridgeEnvFile -PathType Leaf)) {
    throw "Bridge env file does not exist: $BridgeEnvFile"
}

$oldToken = Read-BridgeToken -Path $BridgeEnvFile
if ($ValidateOnly) {
    Get-ScheduledTask -TaskName $BridgeTaskName | Out-Null
    Wait-AuthorizedHealth -BaseUrl $LocalBridgeUrl -Token $oldToken
    Wait-AuthorizedHealth -BaseUrl $ExternalBridgeUrl -Token $oldToken

    $remoteCheck = "sudo sh -c `"grep -c '^MCP_BRIDGE_TOKEN=' '$ProductionDirectory/.env' | grep -qx 1`""
    & ssh -o BatchMode=yes -o ConnectTimeout=15 $SshHost $remoteCheck
    if ($LASTEXITCODE -ne 0) {
        throw "Production MCP_BRIDGE_TOKEN preflight failed"
    }

    Write-Output "MCP bridge rotation preflight passed: local task, both endpoints and production env are ready."
    return
}

$newToken = New-BridgeToken
$localUpdated = $false
$remoteAttempted = $false

try {
    Write-BridgeToken -Path $BridgeEnvFile -Token $newToken
    $localUpdated = $true

    $remoteAttempted = $true
    Set-RemoteBridgeToken -Token $newToken
    Restart-BridgeTask

    Wait-AuthorizedHealth -BaseUrl $LocalBridgeUrl -Token $newToken -MaxAttempts 60
    Wait-AuthorizedHealth -BaseUrl $ExternalBridgeUrl -Token $newToken -MaxAttempts 90
    Assert-TokenRejected -BaseUrl $LocalBridgeUrl -Token $oldToken
    Assert-TokenRejected -BaseUrl $ExternalBridgeUrl -Token $oldToken

    & (Join-Path $PSScriptRoot "production-monitor.ps1") -BaseUrl $InspectorUrl
    if (-not $?) {
        throw "Production monitor failed after bridge token rotation"
    }

    Save-CredentialRecord -Token $newToken
    Write-Output "MCP bridge token rotation passed: both bridge endpoints and Inspector production monitor are healthy."
}
catch {
    $rotationError = $_
    $rollbackErrors = [System.Collections.Generic.List[string]]::new()

    if ($remoteAttempted) {
        try {
            Set-RemoteBridgeToken -Token $oldToken
        }
        catch {
            $rollbackErrors.Add("remote rollback failed")
        }
    }
    if ($localUpdated) {
        try {
            Write-BridgeToken -Path $BridgeEnvFile -Token $oldToken
            Restart-BridgeTask
        }
        catch {
            $rollbackErrors.Add("local rollback failed")
        }
    }
    if ($rollbackErrors.Count -eq 0) {
        try {
            Wait-AuthorizedHealth -BaseUrl $LocalBridgeUrl -Token $oldToken -MaxAttempts 60
            Wait-AuthorizedHealth -BaseUrl $ExternalBridgeUrl -Token $oldToken -MaxAttempts 90
        }
        catch {
            $rollbackErrors.Add("rollback health verification failed")
        }
    }

    $suffix = if ($rollbackErrors.Count -gt 0) { " " + ($rollbackErrors -join '; ') + "." } else { " Rollback completed." }
    throw "MCP bridge token rotation failed: $($rotationError.Exception.Message).$suffix"
}
