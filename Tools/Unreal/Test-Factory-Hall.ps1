param(
    [string]$UnrealPath = 'C:\Program Files\Epic Games\UE_5.8',
    [switch]$NullRHI
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$editor = Join-Path $UnrealPath 'Engine\Binaries\Win64\UnrealEditor.exe'
$arguments = @('"' + (Join-Path $projectRoot 'SmartFactory.uproject') + '"',
    '/Game/SmartFactory/Maps/L_SmartFactoryHall', '-game',
    '-ExecCmds="Automation RunTests SmartFactory.Integration.Hall"',
    '-TestExit="Automation Test Queue Empty"',
    '-unattended', '-NoSplash', '-NoLiveCoding', '-nosound', '-windowed', '-ResX=1600', '-ResY=900',
    '-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=False',
    '-ExecCmds="t.MaxFPS 45,r.DynamicGlobalIlluminationMethod 0,r.ReflectionMethod 0"',
    '"-abslog=' + (Join-Path $projectRoot 'Saved\Logs\FactoryHallRuntime.log') + '"')
if ($NullRHI) { $arguments += '-NullRHI' }
else { $arguments += @('-RenderOffscreen', '-FactoryCapture', '-ForceRes') }
$testStarted = [DateTime]::UtcNow
$process = Start-Process -FilePath $editor -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
Write-Output "Hall integration verification started (PID $($process.Id))."
$process.WaitForExit()
if ($process.ExitCode -ne 0) { throw "Hall verification failed, exit $($process.ExitCode). See Saved\Logs\FactoryHallRuntime.log." }
$reportPath = Join-Path $projectRoot 'Saved\Tests\FactoryHallIntegration.json'
if ((Get-Item -LiteralPath $reportPath).LastWriteTimeUtc -lt $testStarted) { throw 'The hall test did not write a fresh report.' }
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if (-not $report.success) { throw $report.detail }
$report | ConvertTo-Json -Depth 8
