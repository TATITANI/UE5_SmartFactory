param(
    [string]$IsaacPath = 'D:\IsaacSim\4.5.0',
    [switch]$Headless,
    [switch]$Serve,
    [switch]$Export,
    [switch]$Fast,
    [switch]$DryRun,
    [ValidateRange(0,2147483647)][int]$Steps = 0,
    [ValidateRange(1,65532)][int]$BasePort = 9847,
    [string]$OutputPath,
    [string]$StopFile
)
$ErrorActionPreference = 'Stop'
$factoryRoot = Split-Path -Parent $PSScriptRoot
$pythonLauncher = Join-Path $IsaacPath 'python.bat'
$runner = Join-Path $factoryRoot 'run_factory_multi.py'
if (-not (Test-Path -LiteralPath $pythonLauncher)) { throw "Isaac Sim not found at $IsaacPath. Pass -IsaacPath to its installation." }
if (-not (Test-Path -LiteralPath $runner)) { throw "The multi-cell runner is missing: $runner" }
if (-not $OutputPath) { $OutputPath = Join-Path $factoryRoot 'outputs\unreal-multi' }
$absoluteOutput = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
New-Item -ItemType Directory -Force -Path $absoluteOutput | Out-Null
if (-not $StopFile) { $StopFile = Join-Path $absoluteOutput ('stop-' + [guid]::NewGuid().ToString('N') + '.request') }
$absoluteStop = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($StopFile)
if (Test-Path -LiteralPath $absoluteStop) { throw "Stop file already exists. Choose an unused -StopFile path: $absoluteStop" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $absoluteStop) | Out-Null
$factoryArgs = @($runner, '--base-port', "$BasePort", '--output', $absoluteOutput, '--stop-file', $absoluteStop)
if ($Headless) { $factoryArgs += '--headless' }
if ($Serve) { $factoryArgs += '--serve' }
if ($Export) { $factoryArgs += '--export' }
if ($Fast) { $factoryArgs += '--fast' }
if ($DryRun) { $factoryArgs += '--dry-run' }
if ($Steps -gt 0) { $factoryArgs += @('--steps', "$Steps") }
$launchRecord = [ordered]@{
    wrapper_process_id = $PID
    started_utc = [DateTime]::UtcNow.ToString('o')
    runner = $runner
    output_path = $absoluteOutput
    stop_file = $absoluteStop
    base_port = $BasePort
    cell_count = 4
    isaac_process_count = 1
    headless = [bool]$Headless
    controller_only = [bool]$DryRun
    state = 'starting'
}
$launchRecordPath = Join-Path $absoluteOutput 'launch.json'
$launchRecord | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $launchRecordPath -Encoding UTF8
Write-Host "Four independent cells / one Isaac Sim process. Ports $BasePort-$($BasePort + 3)."
Write-Host "For a graceful stop, create this file: $absoluteStop"
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:OMNI_KIT_DISABLE_TELEMETRY = '1'
$factoryExit = 1
Push-Location $IsaacPath
try {
    & $pythonLauncher @factoryArgs
    $factoryExit = $LASTEXITCODE
} finally {
    Pop-Location
    $launchRecord['state'] = 'exited'
    $launchRecord['exit_code'] = $factoryExit
    $launchRecord['finished_utc'] = [DateTime]::UtcNow.ToString('o')
    $launchRecord | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $launchRecordPath -Encoding UTF8
}
exit $factoryExit
