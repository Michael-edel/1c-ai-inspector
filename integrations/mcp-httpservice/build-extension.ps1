param(
    [string]$Designer = 'C:\Program Files (x86)\1cv8\8.3.24.1548\bin\1cv8.exe',
    [string]$BuildBase = 'D:\CodexBuild\mcp-httpservice-build-base',
    [string]$Output = 'D:\CodexBuild\artifacts\MCP_HTTPService_0.9.0.cfe'
)

$ErrorActionPreference = 'Stop'

function Assert-DriveD([string]$Path, [string]$Name) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name must be located on drive D: $fullPath"
    }
    return $fullPath
}

function Invoke-Designer([string[]]$Arguments, [string]$Operation) {
    $process = Start-Process `
        -FilePath $Designer `
        -ArgumentList $Arguments `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "$Operation failed with exit code $($process.ExitCode)."
    }
}

if (-not (Test-Path -LiteralPath $Designer -PathType Leaf)) {
    throw "1C Designer was not found: $Designer"
}

$BuildBase = Assert-DriveD $BuildBase 'BuildBase'
$Output = Assert-DriveD $Output 'Output'
$source = Join-Path $PSScriptRoot 'src'
$configuration = Join-Path $source 'Configuration.xml'
if (-not (Test-Path -LiteralPath $configuration -PathType Leaf)) {
    throw "Extension sources were not found: $configuration"
}

$temp = 'D:\CodexBuild\temp'
New-Item -ItemType Directory -Path $temp -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $Output -Parent) -Force | Out-Null
$env:TEMP = $temp
$env:TMP = $temp

if (-not (Test-Path -LiteralPath (Join-Path $BuildBase '1Cv8.1CD'))) {
    New-Item -ItemType Directory -Path $BuildBase -Force | Out-Null
    $process = Start-Process `
        -FilePath $Designer `
        -ArgumentList @('CREATEINFOBASE', "File=$BuildBase", '/AddInList', 'false') `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if (-not (Test-Path -LiteralPath (Join-Path $BuildBase '1Cv8.1CD'))) {
        throw "Build infobase was not created; exit code $($process.ExitCode)."
    }
}

Invoke-Designer @(
    'DESIGNER',
    "/F`"$BuildBase`"",
    '/DisableStartupDialogs',
    '/DisableStartupMessages',
    '/LoadConfigFromFiles',
    "`"$source`"",
    '-Extension',
    'MCP_HTTPService'
) 'Loading extension sources'

Invoke-Designer @(
    'DESIGNER',
    "/F`"$BuildBase`"",
    '/DisableStartupDialogs',
    '/DisableStartupMessages',
    '/DumpCfg',
    "`"$Output`"",
    '-Extension',
    'MCP_HTTPService'
) 'Building extension artifact'

$hash = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash
Write-Output "Built: $Output"
Write-Output "SHA256: $hash"
