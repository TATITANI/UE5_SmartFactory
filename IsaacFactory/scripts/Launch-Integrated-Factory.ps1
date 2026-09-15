param(
    [string]$IsaacPath = 'D:\IsaacSim\4.5.0',
    [string]$UnrealPath = 'C:\Program Files\Epic Games\UE_5.8',
    [switch]$Build
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$factoryRoot = Join-Path $projectRoot 'IsaacFactory'
$unrealEditor = Join-Path $UnrealPath 'Engine\Binaries\Win64\UnrealEditor.exe'
$projectFile = Join-Path $projectRoot 'SmartFactory.uproject'
$factoryMap = Join-Path $projectRoot 'Content\SmartFactory\Maps\L_SmartFactoryHall.umap'
if (-not (Test-Path -LiteralPath $factoryMap)) { throw 'The saved SmartFactory hall map is missing. Run the Unreal content generation first.' }
$manifestPath = Join-Path $projectRoot 'Binaries\Win64\UnrealEditor.modules'
$logRoot = Join-Path $projectRoot 'Saved\Logs'
$metadataPath = Join-Path $logRoot 'IsaacMultiBackend.json'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
if (-not (Test-Path -LiteralPath $unrealEditor)) { throw "Unreal Editor not found: $unrealEditor" }
if ($Build -or -not (Test-Path -LiteralPath $manifestPath)) {
    & (Join-Path $PSScriptRoot 'Build-Unreal-Bridge.ps1') -UnrealPath $UnrealPath
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$modulePath = Join-Path (Split-Path -Parent $manifestPath) $manifest.Modules.SmartFactory
if (-not (Test-Path -LiteralPath $modulePath)) { throw 'Compiled Unreal module is missing. Launch with -Build.' }

function Test-FiniteFactoryNumber($Value) {
    if ($null -eq $Value -or $Value -is [string] -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { $number = [Convert]::ToDouble($Value, [Globalization.CultureInfo]::InvariantCulture) } catch { return $false }
    return -not [double]::IsNaN($number) -and -not [double]::IsInfinity($number)
}

function Get-FactoryBridgeState([int]$Port, [string]$CellId) {
    $result = [ordered]@{ port = $Port; cell_id = $CellId; state = 'absent'; detail = 'No listener' }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.ConnectAsync('127.0.0.1', $Port)
        try { $connected = $connection.Wait(200) } catch { return [pscustomobject]$result }
        if (-not $connected -or -not $client.Connected) { return [pscustomobject]$result }
        $result['state'] = 'pending'
        $result['detail'] = 'Listener has not supplied a complete snapshot'
        $stream = $client.GetStream()
        $frame = New-Object System.IO.MemoryStream
        $readClock = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $lineComplete = $false
            while ($frame.Length -lt 65536) {
                $remaining = 2000 - [int]$readClock.ElapsedMilliseconds
                if ($remaining -le 0) { return [pscustomobject]$result }
                $client.ReceiveTimeout = [Math]::Max(1, $remaining)
                try { $nextByte = $stream.ReadByte() } catch [System.IO.IOException] { return [pscustomobject]$result }
                if ($nextByte -lt 0) { return [pscustomobject]$result }
                $frame.WriteByte([byte]$nextByte)
                if ($nextByte -eq 10) { $lineComplete = $true; break }
            }
            if (-not $lineComplete) { throw 'Snapshot exceeded the 64 KiB protocol limit.' }
            $decoder = New-Object System.Text.UTF8Encoding($false, $true)
            $message = $decoder.GetString($frame.ToArray()) | ConvertFrom-Json
        } finally { $frame.Dispose() }
        $snapshot = $message.snapshot
        $target = $snapshot.robot_target
        $position = @($target.position)
        $setpoint = $snapshot.conveyor_speed_setpoint
        $configuredSpeed = $message.config.conveyor.speed
        if ($message.type -ne 'snapshot' -or $message.protocol -ne 1 -or
            -not ($message.session_id -is [string]) -or -not $message.session_id -or
            -not (Test-FiniteFactoryNumber $message.sequence) -or $message.sequence -lt 0 -or
            $message.sequence -ne [Math]::Floor([double]$message.sequence) -or
            $snapshot.cell_id -ne $CellId -or $null -eq $snapshot.robot_joint_state -or
            $snapshot.mode -notin @('running', 'paused', 'emergency_stopped', 'bin_full') -or
            $snapshot.state -notin @('conveying','approaching','picking','lifting','transferring','placing','releasing','retracting') -or
            $position.Count -ne 3 -or @($position | Where-Object { -not (Test-FiniteFactoryNumber $_) }).Count -gt 0 -or
            $target.gripper_closed -isnot [bool] -or
            -not (Test-FiniteFactoryNumber $snapshot.simulation_time) -or $snapshot.simulation_time -lt 0 -or
            -not (Test-FiniteFactoryNumber $setpoint) -or $setpoint -lt 0.05 -or $setpoint -gt 1.0 -or
            -not (Test-FiniteFactoryNumber $configuredSpeed) -or
            [Math]::Abs([double]$setpoint - [double]$configuredSpeed) -gt 0.000001) {
            throw 'Listener is not the expected Isaac multi-cell bridge with a valid speed setpoint.'
        }
        $result['state'] = 'ready'
        $result['detail'] = 'Validated Isaac snapshot and conveyor speed setpoint'
        $result['session_id'] = $message.session_id
        $result['sequence'] = $message.sequence
        $result['conveyor_speed_setpoint'] = $setpoint
        return [pscustomobject]$result
    } catch {
        $result['state'] = 'incompatible'
        $result['detail'] = $_.Exception.Message
        return [pscustomobject]$result
    } finally { $client.Dispose() }
}

function Get-AllFactoryBridgeStates {
    foreach ($index in 0..3) { Get-FactoryBridgeState -Port (9847 + $index) -CellId ('Cell{0:00}' -f ($index + 1)) }
}

function Format-BridgeStates($States) {
    return ($States | ForEach-Object { '{0} {1}: {2}' -f $_.cell_id, $_.port, $_.state }) -join '; '
}

$states = @(Get-AllFactoryBridgeStates)
$readyCount = @($states | Where-Object { $_.state -eq 'ready' }).Count
$absentCount = @($states | Where-Object { $_.state -eq 'absent' }).Count
$backendProcess = $null
$backendRecord = [ordered]@{ owned_by_launcher = $false; cell_count = 4; isaac_process_count = 1;
    launcher_process_id = $null; python_process_id = $null; stop_file = $null; output_path = $null;
    checked_utc = [DateTime]::UtcNow.ToString('o'); state = 'starting'; cells = @() }
if ($readyCount -eq 4) {
    # Preserve graceful-stop metadata only if it refers to these exact four sessions.
    if (Test-Path -LiteralPath $metadataPath) {
        try {
            $previous = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
            $sameSessions = @($states | Where-Object {
                $current = $_
                @($previous.cells | Where-Object { $_.port -eq $current.port -and $_.session_id -eq $current.session_id }).Count -ne 1
            }).Count -eq 0
            if ($sameSessions) {
                foreach ($key in @('owned_by_launcher','launcher_process_id','python_process_id','stop_file','output_path')) {
                    $backendRecord[$key] = $previous.$key
                }
            }
        } catch { Write-Warning 'Previous launch metadata could not be reused; running servers were preserved.' }
    }
    Write-Host 'Reusing all four verified Isaac cells on ports 9847-9850.'
} elseif ($absentCount -eq 4) {
    $backendScript = Join-Path $PSScriptRoot 'Run-Factory-Multi.ps1'
    $backendOutput = Join-Path $factoryRoot 'outputs\unreal-multi'
    $stopFile = Join-Path $backendOutput ('stop-' + [guid]::NewGuid().ToString('N') + '.request')
    $backendArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$backendScript`"",
                     '-IsaacPath',"`"$IsaacPath`"",'-Headless','-Serve','-Export','-BasePort','9847',
                     '-OutputPath',"`"$backendOutput`"",'-StopFile',"`"$stopFile`"")
    $backendProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList $backendArgs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot 'IsaacMultiBridge.log') `
        -RedirectStandardError (Join-Path $logRoot 'IsaacMultiBridge-errors.log')
    $backendRecord['owned_by_launcher'] = $true
    $backendRecord['launcher_process_id'] = $backendProcess.Id
    $backendRecord['started_utc'] = [DateTime]::UtcNow.ToString('o')
    $backendRecord['stop_file'] = $stopFile
    $backendRecord['output_path'] = $backendOutput
    $backendRecord | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    Write-Host "One Isaac Sim backend started for four cells. Initialization may take up to 15 minutes. Log: $logRoot\IsaacMultiBridge.log"
} else {
    throw ("Four verified cell servers are required before reuse. Ports are partially occupied or not ready: " +
           (Format-BridgeStates $states) + ". Existing services were left running. Complete their startup or stop them gracefully before retrying.")
}

if ($readyCount -ne 4) {
    $startupClock = [System.Diagnostics.Stopwatch]::StartNew()
    $nextProgressSeconds = 15
    while ($readyCount -ne 4) {
        if ($null -ne $backendProcess -and $backendProcess.HasExited) {
            throw "Isaac multi-cell backend exited. See $logRoot\IsaacMultiBridge-errors.log"
        }
        if ($startupClock.Elapsed.TotalMinutes -ge 15) {
            throw "Isaac initialization timed out; the backend was left running. Graceful-stop metadata: $metadataPath"
        }
        if ($startupClock.Elapsed.TotalSeconds -ge $nextProgressSeconds) {
            Write-Host (("Waiting for four Isaac scenes: {0:mm\:ss} / 15:00. " -f $startupClock.Elapsed) + (Format-BridgeStates $states))
            $nextProgressSeconds = $startupClock.Elapsed.TotalSeconds + 15
        }
        Start-Sleep -Seconds 2
        $states = @(Get-AllFactoryBridgeStates)
        if (@($states | Where-Object { $_.state -eq 'incompatible' }).Count -gt 0) {
            throw ("An incompatible listener appeared during startup: " + (Format-BridgeStates $states) + ". No service was terminated.")
        }
        $readyCount = @($states | Where-Object { $_.state -eq 'ready' }).Count
    }
    Write-Host 'All four Isaac scenes and their speed setpoints are verified.'
}
$backendRecord['state'] = 'ready'
$backendRecord['cells'] = $states
$backendRecord['checked_utc'] = [DateTime]::UtcNow.ToString('o')
if ($backendRecord.output_path) {
    $reportFile = Join-Path $backendRecord.output_path 'report.json'
    if (Test-Path -LiteralPath $reportFile) {
        try {
            $report = Get-Content -LiteralPath $reportFile -Raw | ConvertFrom-Json
            if ($report.process_id) { $backendRecord['python_process_id'] = $report.process_id }
            elseif ($report.pid) { $backendRecord['python_process_id'] = $report.pid }
        } catch { Write-Warning 'Live backend process metadata is not yet readable.' }
    }
}
$backendRecord | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
$unrealArgs = @("`"$projectFile`"",'/Game/SmartFactory/Maps/L_SmartFactoryHall',
                '-game','-windowed','-ResX=1600','-ResY=900','-NoSplash','-NoLiveCoding','-nosound',
                '-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=False',
                '-ExecCmds="t.MaxFPS 45,r.DynamicGlobalIlluminationMethod 0,r.ReflectionMethod 0"',
                "`"-abslog=$(Join-Path $logRoot 'UnrealFactory.log')`"")
Start-Process -FilePath $unrealEditor -ArgumentList $unrealArgs -WorkingDirectory $projectRoot | Out-Null
Write-Host "Unreal factory hall launched. Select CELL 01-04 and verify LIVE for each cell. Backend metadata: $metadataPath"
