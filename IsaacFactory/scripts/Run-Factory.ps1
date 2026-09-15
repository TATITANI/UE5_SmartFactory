param(
    [string]$IsaacPath = 'D:\IsaacSim\4.5.0',
    [switch]$Headless,
    [ValidateRange(0,2147483647)][int]$Cycles = 0,
    [ValidateRange(0,2147483647)][int]$Steps = 0,
    [switch]$Fast,
    [switch]$Capture,
    [switch]$Export,
    [switch]$DryRun,
    [switch]$UnrealBridge,
    [switch]$Serve,
    [ValidateRange(1,65535)][int]$BridgePort = 9847,
    [string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$factoryRoot = Split-Path -Parent $PSScriptRoot
$pythonLauncher = Join-Path $IsaacPath 'python.bat'
if (-not (Test-Path -LiteralPath $pythonLauncher)) {
    throw "Isaac Sim not found at $IsaacPath. Run scripts\Install-IsaacSim.ps1 first, or pass -IsaacPath."
}
$factoryArgs = @((Join-Path $factoryRoot 'run_factory.py'))
if ($Headless) { $factoryArgs += '--headless' }
if ($Fast) { $factoryArgs += '--fast' }
if ($DryRun) { $factoryArgs += '--dry-run' }
if ($UnrealBridge) { $factoryArgs += @('--unreal-bridge', '--bridge-port', "$BridgePort") }
if ($Serve) { $factoryArgs += '--serve' }
if ($OutputPath) {
    $absoluteOutputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
    $factoryArgs += @('--output', $absoluteOutputPath)
}
if ($Cycles -gt 0) { $factoryArgs += @('--cycles', "$Cycles") }
if ($Steps -gt 0) { $factoryArgs += @('--steps', "$Steps") }
if ($Capture) { $factoryArgs += '--capture' }
if ($Export) { $factoryArgs += '--export' }
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:OMNI_KIT_DISABLE_TELEMETRY = '1'
Push-Location $IsaacPath
try {
    & $pythonLauncher @factoryArgs
    $factoryExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $factoryExit
