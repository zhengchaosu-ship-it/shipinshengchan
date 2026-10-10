$ErrorActionPreference = 'Stop'
$taskName = 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER'
$taskProjectRoot = Split-Path $PSScriptRoot -Parent
$taskConfigPath = Join-Path $PSScriptRoot 'local_ui_worker.config.json'
$taskWorkerConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($taskWorkerConfig.windows_user_sid -ne $taskIdentity.User.Value -or $taskWorkerConfig.windows_user -ne $taskIdentity.Name) {
    throw 'WINDOWS_USER_MISMATCH'
}
if ($taskWorkerConfig.worker_enabled -ne $true -or $taskWorkerConfig.dry_run_mode -ne $true -or $taskWorkerConfig.real_submit_armed -ne $false) {
    throw 'INSTALL_REQUIRES_UNARMED_DRY_RUN'
}
$taskPython = (Get-Content -LiteralPath (Join-Path $taskProjectRoot 'config.json') -Raw | ConvertFrom-Json).paths.python_executable
$taskPythonWindowless = Join-Path (Split-Path $taskPython -Parent) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $taskPythonWindowless -PathType Leaf)) { throw 'CONFIGURED_PYTHONW_NOT_FOUND' }
$taskArguments = '-X utf8 -m xiaovcat_publish_worker --config "' + $taskConfigPath + '"'
$taskAction = New-ScheduledTaskAction -Execute $taskPythonWindowless -Argument $taskArguments -WorkingDirectory $taskProjectRoot
$taskExisting = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$taskDescription = 'XunZhen LOCAL_UI_PUBLISH_WORKER_V1: initial DRY_RUN, real_submit_armed=false; only configured Plan/Job scope.'
if ($taskExisting) {
    if ($taskExisting.Actions.Execute -eq $taskPythonWindowless -and $taskExisting.Actions.Arguments -eq $taskArguments -and $taskExisting.Description -eq $taskDescription) {
        Write-Output 'EXISTING_LOCAL_UI_WORKER_TASK_PRESERVED'
        exit 0
    }
    $taskMonitorArguments = '-X utf8 -m xiaovcat_adapter.desktop_worker.resident_monitor --config "' + (Join-Path $PSScriptRoot 'desktop_worker\resident_monitor.config.json') + '"'
    $taskMonitorDescription = 'XunZhen MONITOR_ONLY: readonly queue/heartbeat; no claim, no UI input, no publish. NOT production execution ready.'
    if ($taskExisting.Description -ne $taskMonitorDescription -or $taskExisting.Actions.Execute -ne $taskPythonWindowless -or $taskExisting.Actions.Arguments -ne $taskMonitorArguments -or $taskExisting.State -eq 'Running') {
        throw 'EXISTING_TASK_NOT_OUR_STOPPED_MONITOR_NO_OVERWRITE'
    }
    $taskBackupRoot = $taskWorkerConfig.runtime_dir
    New-Item -ItemType Directory -Path $taskBackupRoot -Force | Out-Null
    Export-ScheduledTask -TaskName $taskName | Out-File -LiteralPath (Join-Path $taskBackupRoot ('task-before-local-worker-' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.xml')) -Encoding utf8
    $taskExisting.Actions = @($taskAction)
    $taskExisting.Description = $taskDescription
    Set-ScheduledTask -InputObject $taskExisting | Select-Object TaskName,State
    Write-Output 'OWNED_MONITOR_TASK_MIGRATED_TO_UNARMED_LOCAL_WORKER'
    exit 0
}
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskIdentity.Name
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskIdentity.Name -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description $taskDescription | Select-Object TaskName,State
