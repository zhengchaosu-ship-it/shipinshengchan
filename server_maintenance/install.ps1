$ErrorActionPreference = 'Stop'
$workspacePath = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
if (-not (Test-Path -LiteralPath (Join-Path $workspacePath 'server_maintenance\precheck.py'))) { throw 'WORKSPACE_PATH_INVALID' }
$reportPath = Join-Path $workspacePath 'runtime\maintenance_watchdog'
$taskBackupPath = Join-Path $reportPath 'task_baseline'
New-Item -ItemType Directory -Force $taskBackupPath | Out-Null
$pythonwPath = Join-Path $workspacePath '.venv-cuda-test\Scripts\pythonw.exe'
foreach ($role in @('planner','api')) {
    $taskName = if ($role -eq 'planner') { 'STARTUP_AUTOPILOT_PRODUCTION_SERVER_01' } else { 'XunZhen-Startup-Render-server' }
    $task = Get-ScheduledTask -TaskName $taskName
    $baseline = Join-Path $taskBackupPath ($role+'.xml')
    if (-not (Test-Path -LiteralPath $baseline)) { Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath $baseline -Encoding UTF8 }
    if ($task.Actions.Execute -ne $pythonwPath) { throw 'FORMAL_EXECUTABLE_MISMATCH' }
    $expectedModule = if ($role -eq 'planner') { 'startup_autopilot.production_worker' } else { 'startup_render.lan_server' }
    if ($task.Actions.Arguments -notlike ('*-m '+$expectedModule+' *') -and $task.Actions.Arguments -notlike ('*-m server_maintenance.service --role '+$role+'*')) { throw 'FORMAL_ACTION_MISMATCH' }
    # 使用原正式任务/用户/触发器；动作加日志监督入口，现有进程不在这里停止。
    $task.Actions = @(New-ScheduledTaskAction -Execute $pythonwPath -Argument ('-X utf8 -B -m server_maintenance.service --role '+$role) -WorkingDirectory $workspacePath)
    $task.Settings.RestartCount = 3
    $task.Settings.RestartInterval = 'PT1M'
    $task.Settings.MultipleInstances = 'IgnoreNew'
    $task.Settings.ExecutionTimeLimit = 'PT0S'
    $task.Settings.StartWhenAvailable = $true
    $task | Set-ScheduledTask | Out-Null
}
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
foreach ($mode in @('minute','full')) {
    $taskName = if ($mode -eq 'minute') { 'XUNZHEN_SERVER_LOCAL_GUARD_V2' } else { 'XUNZHEN_SERVER_MAINTENANCE_SNAPSHOT_V2' }
    $interval = if ($mode -eq 'minute') { New-TimeSpan -Minutes 1 } else { New-TimeSpan -Minutes 30 }
    $arguments = '-X utf8 -B "'+(Join-Path $workspacePath 'server_maintenance\collector.py')+'" --repair'
    if ($mode -eq 'minute') { $arguments += ' --minute --no-size-scan' }
    $action = New-ScheduledTaskAction -Execute $pythonwPath -Argument $arguments -WorkingDirectory $workspacePath
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval $interval
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '寻帧服务器本地守护；不依赖Codex，不执行发布/迁移/未知删除。' -Force | Out-Null
}
Get-ScheduledTask -TaskName 'STARTUP_AUTOPILOT_PRODUCTION_SERVER_01','XunZhen-Startup-Render-server','XUNZHEN_SERVER_LOCAL_GUARD_V2','XUNZHEN_SERVER_MAINTENANCE_SNAPSHOT_V2' | Select-Object TaskName,State
