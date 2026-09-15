param([string]$InstallPath = 'D:\IsaacSim\4.5.0')
$ErrorActionPreference = 'Stop'
$factoryRoot = Split-Path -Parent $PSScriptRoot
$downloadRoot = Join-Path $factoryRoot 'downloads'
$archive = Join-Path $downloadRoot 'isaac-sim-standalone-4.5.0-windows-x86_64.zip'
$source = 'https://download.isaacsim.omniverse.nvidia.com/isaac-sim-standalone-4.5.0-windows-x86_64.zip'
$expectedBytes = 7013544567L
$resolvedInstall = [IO.Path]::GetFullPath($InstallPath)
$completeMarker = Join-Path $resolvedInstall '.factory-install-complete.json'
$progressMarker = Join-Path $resolvedInstall '.factory-install-in-progress.json'
if ((Test-Path -LiteralPath $completeMarker) -and
    (Test-Path -LiteralPath (Join-Path $resolvedInstall 'python.bat')) -and
    (Test-Path -LiteralPath (Join-Path $resolvedInstall 'kit\kit.exe'))) {
    Write-Host "Isaac Sim already exists at $resolvedInstall"
    exit 0
}
if ((Test-Path -LiteralPath $resolvedInstall) -and
    (Get-ChildItem -LiteralPath $resolvedInstall -Force | Select-Object -First 1) -and
    -not (Test-Path -LiteralPath $progressMarker)) {
    throw "Install directory is non-empty and not owned by this installer. Choose an empty directory: $resolvedInstall"
}
New-Item -ItemType Directory -Force -Path $downloadRoot,$resolvedInstall | Out-Null
@{version='4.5.0'; source=$source} | ConvertTo-Json | Set-Content -LiteralPath $progressMarker -Encoding UTF8
if (-not (Test-Path -LiteralPath $archive) -or (Get-Item -LiteralPath $archive).Length -ne $expectedBytes) {
    & curl.exe -L --fail --retry 4 --continue-at - --output $archive $source
    if ($LASTEXITCODE -ne 0) { throw 'NVIDIA archive download failed.' }
}
if ((Get-Item -LiteralPath $archive).Length -ne $expectedBytes) { throw 'Unexpected archive size.' }
Write-Host 'Extracting Isaac Sim 4.5.0. This may take several minutes.'
& tar.exe -xf $archive -C $resolvedInstall
if ($LASTEXITCODE -ne 0) { throw 'Archive extraction failed.' }
if (-not (Test-Path -LiteralPath (Join-Path $resolvedInstall 'python.bat'))) { throw 'Missing Python launcher after extraction.' }
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
$installation = @{
    version = '4.5.0'
    path = $resolvedInstall
    source = $source
    bytes = $expectedBytes
    sha256_local = $archiveHash
    installed_at = (Get-Date).ToString('o')
} | ConvertTo-Json
$installation | Set-Content -LiteralPath (Join-Path $factoryRoot 'local-install.json') -Encoding UTF8
$installation | Set-Content -LiteralPath $completeMarker -Encoding UTF8
Remove-Item -LiteralPath $progressMarker
Write-Host "Installed at $resolvedInstall"
Write-Host 'Start the project with Launch-Factory.bat.'
