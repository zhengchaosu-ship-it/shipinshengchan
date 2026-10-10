$ErrorActionPreference = 'Stop'
$services = @{
    planner = @{ Task='STARTUP_AUTOPILOT_PRODUCTION_SERVER_01'; Module='startup_autopilot.production_worker' }
    api = @{ Task='XunZhen-Startup-Render-server'; Module='startup_render.lan_server' }
    account_sync = @{ Task='YIXIAOER_ACCOUNT_SYNC_SERVER_01'; Module='yixiaoer_adapter.account_sync_worker' }
}
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' })
$result = @{}
foreach ($role in $services.Keys) {
    $spec = $services[$role]
    $matches = @($processes | Where-Object { $_.CommandLine -like ('*-m '+$spec.Module+' *') -or $_.CommandLine -like ('*-m server_maintenance.service --role '+$role+'*') -or ($_.CommandLine -like '*-m server_maintenance.child_service *' -and $_.CommandLine -like ('*--module '+$spec.Module+' *')) })
    # venv启动器和实际Python是同一个实例；独立根进程才计数。
    $ids = @($matches | ForEach-Object { $_.ProcessId })
    $roots = @($matches | Where-Object { $_.ParentProcessId -notin $ids })
    $task = Get-ScheduledTask -TaskName $spec.Task
    $info = Get-ScheduledTaskInfo -TaskName $spec.Task
    $result[$role] = @{
        instance_count=$roots.Count
        pids=@($matches | ForEach-Object { $_.ProcessId })
        task_name=$spec.Task
        task_state=[string]$task.State
        task_enabled=[bool]$task.Settings.Enabled
        restart_count=$task.Settings.RestartCount
        restart_interval=$task.Settings.RestartInterval
        multiple_instances=[string]$task.Settings.MultipleInstances
        last_task_result=$info.LastTaskResult
        wrapper_count=@($matches | Where-Object { $_.CommandLine -like ('*-m server_maintenance.service --role '+$role+'*') -and $_.ParentProcessId -notin $ids }).Count
    }
}
$result | ConvertTo-Json -Depth 5 -Compress
