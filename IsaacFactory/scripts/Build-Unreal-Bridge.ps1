param([string]$UnrealPath = 'C:\Program Files\Epic Games\UE_5.8')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$buildScript = Join-Path $UnrealPath 'Engine\Build\BatchFiles\Build.bat'
$projectFile = Join-Path $projectRoot 'SmartFactory.uproject'
if (-not (Test-Path -LiteralPath $buildScript)) { throw "Unreal Build.bat not found: $buildScript" }
# Give every build a new binary name so an open editor's loaded DLL is preserved.
do { $moduleSuffix = Get-Random -Minimum 10000 -Maximum 99999 }
while (Test-Path -LiteralPath (Join-Path $projectRoot "Binaries\Win64\UnrealEditor-SmartFactory-$moduleSuffix.dll"))
& $buildScript SmartFactoryEditor Win64 Development "-Project=$projectFile" "-ModuleWithSuffix=SmartFactory,$moduleSuffix" -NoHotReloadFromIDE -WaitMutex
if ($LASTEXITCODE -ne 0) { throw 'Unreal integration build failed.' }
