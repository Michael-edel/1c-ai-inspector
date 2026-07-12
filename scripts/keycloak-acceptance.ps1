param([switch]$KeepRunning, [switch]$Build)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
$adminPassword = $null
$containerStackStarted = $false
try {
    $randomBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    $adminPassword = [Convert]::ToBase64String($randomBytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    $maintainerPassword = [Convert]::ToBase64String($randomBytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    $ownerPassword = [Convert]::ToBase64String($randomBytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    $packageSecret = [Convert]::ToBase64String($randomBytes)

    $env:KEYCLOAK_ADMIN_USERNAME = "inspector-admin"
    $env:KEYCLOAK_ADMIN_PASSWORD = $adminPassword
    $env:INSPECTOR_AUTH_MODE = "jwks"
    $env:AUTH_JWKS_URL = "http://keycloak:8080/realms/inspector/protocol/openid-connect/certs"
    $env:AUTH_ISSUER = "http://localhost:8081/realms/inspector"
    $env:AUTH_AUDIENCE = "inspector-api"
    $env:AUTH_ROLES_CLAIM = "realm_access.roles"
    $env:AUTH_SUBJECT_CLAIM = "sub"
    $env:INSPECTOR_PACKAGE_SIGNING_SECRET = $packageSecret

    $composeArgs = @("--env-file", ".env", "-f", "docker-compose.yml", "-f", "docker-compose.keycloak.yml", "up")
    if ($Build) { $composeArgs += "--build" }
    $composeArgs += "-d"
    docker compose @composeArgs
    if ($LASTEXITCODE -ne 0) { throw "Keycloak Compose startup failed" }
    $containerStackStarted = $true

    $wellKnown = "http://127.0.0.1:8081/realms/inspector/.well-known/openid-configuration"
    $deadline = (Get-Date).AddMinutes(2)
    do {
        try {
            $oidc = Invoke-RestMethod -Uri $wellKnown
            if ($oidc.token_endpoint) { break }
        } catch { Start-Sleep -Seconds 2 }
    } while ((Get-Date) -lt $deadline)
    if (-not $oidc -or -not $oidc.token_endpoint) { throw "Keycloak OIDC endpoint timeout" }

    $adminToken = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/realms/master/protocol/openid-connect/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        client_id = "admin-cli"
        username = $env:KEYCLOAK_ADMIN_USERNAME
        password = $adminPassword
        grant_type = "password"
    }
    $adminHeaders = @{ Authorization = "Bearer $($adminToken.access_token)" }

    function New-InspectorUser([string]$Username, [string]$Password, [string]$Role) {
        $userBody = @{
            username = $Username
            enabled = $true
            email = "$Username@local.test"
            emailVerified = $true
            requiredActions = @()
        } | ConvertTo-Json -Depth 10
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/admin/realms/inspector/users" -Headers $adminHeaders -ContentType "application/json" -Body $userBody | Out-Null
        $users = @(Invoke-RestMethod -Uri "http://127.0.0.1:8081/admin/realms/inspector/users?username=$Username&exact=true" -Headers $adminHeaders)
        if ($users.Count -ne 1) { throw "Keycloak user creation failed" }
        $userId = $users[0].id
        $profileBody = @{
            enabled = $true
            email = "$Username@local.test"
            emailVerified = $true
            firstName = "Inspector"
            lastName = $Role
            requiredActions = @()
        } | ConvertTo-Json -Depth 10
        Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8081/admin/realms/inspector/users/$userId" -Headers $adminHeaders -ContentType "application/json" -Body $profileBody | Out-Null
        $passwordBody = @{ type = "password"; value = $Password; temporary = $false } | ConvertTo-Json
        Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8081/admin/realms/inspector/users/$userId/reset-password" -Headers $adminHeaders -ContentType "application/json" -Body $passwordBody | Out-Null
        $roleObject = Invoke-RestMethod -Uri "http://127.0.0.1:8081/admin/realms/inspector/roles/$Role" -Headers $adminHeaders
        $roleBody = ConvertTo-Json -InputObject @($roleObject) -Depth 10
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/admin/realms/inspector/users/$userId/role-mappings/realm" -Headers $adminHeaders -ContentType "application/json" -Body $roleBody | Out-Null
    }

    New-InspectorUser "inspector-maintainer" $maintainerPassword "maintainer"
    New-InspectorUser "inspector-owner" $ownerPassword "owner"
    .\scripts\idp-jwks-acceptance.ps1 -JwksUrl "http://127.0.0.1:8081/realms/inspector/protocol/openid-connect/certs" -Issuer $env:AUTH_ISSUER -Audience $env:AUTH_AUDIENCE

    $maintainerToken = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/realms/inspector/protocol/openid-connect/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        client_id = "inspector-api"
        username = "inspector-maintainer"
        password = $maintainerPassword
        grant_type = "password"
        scope = "openid"
    }).access_token
    $ownerToken = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/realms/inspector/protocol/openid-connect/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        client_id = "inspector-api"
        username = "inspector-owner"
        password = $ownerPassword
        grant_type = "password"
        scope = "openid"
    }).access_token
    .\scripts\v05-acceptance.ps1 -AuthToken $maintainerToken -OwnerToken $ownerToken
    Write-Output "Keycloak acceptance passed: local IdP, real JWKS validation and JWT role-based proposal flow verified."
} finally {
    if ($containerStackStarted -and -not $KeepRunning) {
        docker compose --env-file .env -f docker-compose.yml -f docker-compose.keycloak.yml down | Out-Null
    }
    Pop-Location
}
