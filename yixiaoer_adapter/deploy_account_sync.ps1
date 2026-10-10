$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$configurationPath = Join-Path $PSScriptRoot 'account_sync.config.json'
$configuration = Get-Content -LiteralPath $configurationPath -Raw | ConvertFrom-Json
$taskName = 'YIXIAOER_ACCOUNT_SYNC_SERVER_01'
$arguments = '-X utf8 -m yixiaoer_adapter.account_sync_worker --config "' + $configurationPath + '"'
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    if ($existingTask.Actions.Execute -ne $configuration.pythonw -or $existingTask.Actions.Arguments -ne $arguments) {
        throw 'EXISTING_ACCOUNT_SYNC_TASK_COMMAND_MISMATCH'
    }
} else {
    $action = New-ScheduledTaskAction -Execute $configuration.pythonw -Argument $arguments -WorkingDirectory $workspacePath
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
    $principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '蚁小二账号只读自动同步：启动一次、每5分钟、手动请求；不生成、不渲染、不发布。' | Out-Null
}
if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') { Start-ScheduledTask -TaskName $taskName }
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
