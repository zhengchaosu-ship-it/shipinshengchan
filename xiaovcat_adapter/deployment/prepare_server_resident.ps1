# 仅准备Disabled任务；不启动Worker、不启动小V猫、不武装提交。
$ErrorActionPreference = 'Stop'
$publishProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$publishConfig = Join-Path $publishProjectRoot 'xiaovcat_adapter\server_ui_worker.config.json'
$publishSettings = Get-Content -LiteralPath $publishConfig -Encoding UTF8 -Raw | ConvertFrom-Json
if ($publishSettings.worker_enabled -or !$publishSettings.dry_run_mode -or $publishSettings.real_submit_armed) {
    throw 'SERVER_PREPARATION_MUST_BE_DISABLED_AND_UNARMED'
}
if ([System.Net.Dns]::GetHostName() -ne $publishSettings.hostname) { throw 'SERVER_HOST_MISMATCH' }
$publishUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($publishUserSid -ne $publishSettings.windows_user_sid) { throw 'SERVER_USER_MISMATCH' }
$publishPython = (Get-Content -LiteralPath (Join-Path $publishProjectRoot 'config.json') -Encoding UTF8 -Raw | ConvertFrom-Json).paths.python_executable
$publishPythonWindowless = Join-Path (Split-Path -Parent $publishPython) 'pythonw.exe'
if (!(Test-Path -LiteralPath $publishPythonWindowless -PathType Leaf)) { throw 'PYTHONW_NOT_FOUND' }
$publishTaskName = 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER_SERVER'
$publishExistingTask = Get-ScheduledTask -TaskName $publishTaskName -ErrorAction SilentlyContinue
if ($publishExistingTask) { throw 'SERVER_TASK_ALREADY_EXISTS_NO_OVERWRITE' }
$publishTaskAction = New-ScheduledTaskAction -Execute $publishPythonWindowless -Argument ('-X utf8 -B -m xiaovcat_publish_worker --config "'+$publishConfig+'"') -WorkingDirectory $publishProjectRoot
$publishTaskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $publishSettings.windows_user
$publishTaskPrincipal = New-ScheduledTaskPrincipal -UserId $publishSettings.windows_user -LogonType Interactive
$publishTaskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
$publishTaskSettings.Enabled = $false
$publishTask = New-ScheduledTask -Action $publishTaskAction -Trigger $publishTaskTrigger -Principal $publishTaskPrincipal -Settings $publishTaskSettings -Description 'Server-only confirmed PublishJob executor; disabled pending original Job3 acceptance'
Register-ScheduledTask -TaskName $publishTaskName -InputObject $publishTask | Out-Null
Get-ScheduledTask -TaskName $publishTaskName | Select-Object TaskName, State, @{n='Enabled';e={$_.Settings.Enabled}}, @{n='User';e={$_.Principal.UserId}}, @{n='Logon';e={[string]$_.Principal.LogonType}}
