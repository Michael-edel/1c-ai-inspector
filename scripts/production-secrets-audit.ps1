param(
    [string]$EnvFile = ".env",
    [switch]$WithKeycloak
)

$ErrorActionPreference = "Stop"
$values = @{}
Get-Content -LiteralPath (Resolve-Path -LiteralPath $EnvFile -ErrorAction Stop) | ForEach-Object {
    if ($_ -match "^\s*([^#=][^=]*)=(.*)$") {
        $values[$matches[1].Trim()] = $matches[2].Trim()
    }
}

$minimumLengths = @{
    POSTGRES_ADMIN_PASSWORD = 24
    MIGRATION_DB_PASSWORD = 24
    RUNTIME_DB_PASSWORD = 24
    MODEL_API_KEY = 16
    INSPECTOR_PACKAGE_SIGNING_SECRET = 32
}
if ($values["INSPECTOR_AUTH_MODE"] -ne "jwks") {
    $minimumLengths["INSPECTOR_AUTH_SECRET"] = 32
}
if ($values["MCP_TRANSPORT"] -eq "bridge") {
    $minimumLengths["MCP_BRIDGE_TOKEN"] = 16
}
if ($WithKeycloak) {
    $minimumLengths["KEYCLOAK_DB_PASSWORD"] = 24
    $minimumLengths["KEYCLOAK_ADMIN_PASSWORD"] = 24
}

$failures = [System.Collections.Generic.List[string]]::new()
$seen = @{}
foreach ($item in $minimumLengths.GetEnumerator()) {
    $key = $item.Key
    $value = $values[$key]
    if ([string]::IsNullOrWhiteSpace($value)) {
        $failures.Add("missing:$key")
        continue
    }
    if ($value -match "(?i)replace-with|change-me|example|your-|password123") {
        $failures.Add("placeholder:$key")
    }
    if ($value.Length -lt [int]$item.Value) {
        $failures.Add("short:$key")
    }
    if ($seen.ContainsKey($value)) {
        $failures.Add("duplicate:${key}:$($seen[$value])")
    } else {
        $seen[$value] = $key
    }
}

if ($failures.Count -gt 0) {
    throw "Production secret audit failed without printing values: $($failures -join ', ')"
}

Write-Output "Production secret audit passed: required secrets are configured, sufficiently long and not duplicated. Values were not printed."
