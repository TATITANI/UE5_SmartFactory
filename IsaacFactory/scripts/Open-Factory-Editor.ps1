param([string]$UnrealPath = 'C:\Program Files\Epic Games\UE_5.8', [switch]$SaveInitialView, [switch]$SingleCell)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$editorPath = Join-Path $UnrealPath 'Engine\Binaries\Win64\UnrealEditor.exe'
$projectFile = Join-Path $projectRoot 'SmartFactory.uproject'
$mapName = if ($SingleCell) { 'L_SmartFactory' } else { 'L_SmartFactoryHall' }
$mapFile = Join-Path $projectRoot ('Content\SmartFactory\Maps\' + $mapName + '.umap')
$mapPath = '/Game/SmartFactory/Maps/' + $mapName
$previewScript = (Join-Path $projectRoot 'Tools\Unreal\open_factory_editor.py').Replace('\','/')
if (-not (Test-Path -LiteralPath $editorPath)) { throw "Unreal Editor not found: $editorPath" }
if (-not (Test-Path -LiteralPath $mapFile)) { throw 'The saved factory map is missing.' }
$previewCommand = 'py ' + $previewScript
if ($SaveInitialView) { $previewCommand += ' --save-editor-view' }
if ($SingleCell) { $previewCommand += ' --single-cell' }
$editorArgs = @("`"$projectFile`"",$mapPath,'-NoSplash','-NoLiveCoding',
    '-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=False',
    ('-ExecCmds="t.MaxFPS 30,r.DynamicGlobalIlluminationMethod 0,r.ReflectionMethod 0,' + $previewCommand + '"'),
    ('"-abslog=' + (Join-Path $projectRoot 'Saved\Logs\FactoryEditor.log') + '"'))
Start-Process -FilePath $editorPath -ArgumentList $editorArgs -WorkingDirectory $projectRoot | Out-Null
Write-Host "Opened $mapName in Unreal Editor. The authored factory is visible before Play."
