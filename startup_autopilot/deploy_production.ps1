$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$configurationPath = Join-Path $PSScriptRoot 'production_worker.config.json'
$configuration = Get-Content -LiteralPath $configurationPath -Raw | ConvertFrom-Json
$taskName = 'STARTUP_AUTOPILOT_PRODUCTION_SERVER_01'
$arguments = '-X utf8 -m startup_autopilot.production_worker --config "' + $configurationPath + '"'
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    if ($existingTask.Actions.Execute -ne $configuration.pythonw -or $existingTask.Actions.Arguments -ne $arguments) {
        throw 'EXISTING_AUTOPILOT_TASK_COMMAND_MISMATCH'
    }
} else {
    $action = New-ScheduledTaskAction -Execute $configuration.pythonw -Argument $arguments -WorkingDirectory $workspacePath
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
    $principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '正式起号托管：仅消费员工本人长期授权，每日额度持久化，复用2060S Render和蚁小二LOCAL提交一次。' | Out-Null
}
if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') { Start-ScheduledTask -TaskName $taskName }
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
