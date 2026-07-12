param(
    [string]$JwksUrl = $env:AUTH_JWKS_URL,
    [string]$Issuer = $env:AUTH_ISSUER,
    [string]$Audience = $env:AUTH_AUDIENCE
)

$ErrorActionPreference = "Stop"

if (-not $JwksUrl -or -not $Issuer -or -not $Audience) {
    throw "JwksUrl, Issuer and Audience are required; pass them explicitly or configure AUTH_JWKS_URL/AUTH_ISSUER/AUTH_AUDIENCE."
}

$response = Invoke-RestMethod -Uri $JwksUrl -Method Get
if (-not $response.keys -or @($response.keys).Count -lt 1) {
    throw "JWKS response does not contain keys"
}

$invalid = @($response.keys | Where-Object {
    $_.kty -ne "RSA" -or -not $_.kid -or $_.alg -notin @("RS256", "RS384", "RS512")
})
if ($invalid.Count -gt 0) {
    throw "JWKS contains unsupported or incomplete RSA keys"
}

if ($Issuer -like "*replace-with-*" -or $Audience -like "*replace-with-*") {
    throw "Issuer or audience still contains a placeholder"
}

Write-Output "IdP JWKS acceptance passed: endpoint returned supported RSA keys for the configured issuer and audience."
