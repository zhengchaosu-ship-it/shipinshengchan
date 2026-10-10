$ErrorActionPreference = 'Stop'
$taskName = 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskLauncher = Join-Path $PSScriptRoot 'start_resident_monitor.ps1'
$taskPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskOldArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $taskLauncher + '"'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskConfigPath = Join-Path $PSScriptRoot 'resident_monitor.config.json'
$taskMonitorConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
if ($taskMonitorConfig.mode -ne 'MONITOR_ONLY' -or $taskMonitorConfig.real_publish_enabled -ne $false) {
    throw 'RESIDENT_EXECUTION_NOT_IMPLEMENTED_MONITOR_ONLY'
}
$taskPython = (Get-Content -LiteralPath (Join-Path $taskProjectRoot 'config.json') -Raw | ConvertFrom-Json).paths.python_executable
$taskPythonWindowless = Join-Path (Split-Path $taskPython -Parent) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $taskPythonWindowless -PathType Leaf)) {
    throw 'CONFIGURED_PYTHONW_NOT_FOUND'
}
$taskArguments = '-X utf8 -m xiaovcat_adapter.desktop_worker.resident_monitor --config "' + $taskConfigPath + '"'
$taskDescription = 'XunZhen MONITOR_ONLY: readonly queue/heartbeat; no claim, no UI input, no publish. NOT production execution ready.'
$taskAction = New-ScheduledTaskAction -Execute $taskPythonWindowless -Argument $taskArguments -WorkingDirectory $taskProjectRoot
$taskExisting = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($taskExisting) {
    if ($taskExisting.Actions.Execute -eq $taskPythonWindowless -and $taskExisting.Actions.Arguments -eq $taskArguments) {
        Write-Output 'EXISTING_MONITOR_TASK_PRESERVED'
        exit 0
    }
    # 只迁移本轮创建的只读监控任务，不覆盖其它同名生产任务。
    if ($taskExisting.Description -eq $taskDescription -and $taskExisting.Actions.Execute -eq $taskPowerShell -and $taskExisting.Actions.Arguments -eq $taskOldArguments -and $taskExisting.State -ne 'Running') {
        Set-ScheduledTask -TaskName $taskName -Action $taskAction | Select-Object TaskName,State
        Write-Output 'OWNED_MONITOR_ACTION_UPDATED_TO_PYTHONW'
        exit 0
    }
    throw 'EXISTING_TASK_NOT_OUR_STOPPED_MONITOR_NO_OVERWRITE'
}
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskIdentity
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskIdentity -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description $taskDescription | Select-Object TaskName,State
