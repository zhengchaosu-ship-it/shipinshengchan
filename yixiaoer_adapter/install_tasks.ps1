$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$taskConfig=Get-Content -LiteralPath (Join-Path $taskRoot 'yixiaoer_adapter\worker.config.json') -Raw | ConvertFrom-Json
if ([Environment]::MachineName -ne $taskConfig.hostname) { throw 'SERVER_PUBLISH_NODE_REQUIRED' }
if ([Security.Principal.WindowsIdentity]::GetCurrent().Name -notmatch '\\Administrator$') { throw 'ADMINISTRATOR_REQUIRED' }
$taskPrincipal=New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
$taskTrigger=New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
$clientAction=New-ScheduledTaskAction -Execute $taskConfig.client_executable -WorkingDirectory (Split-Path -Parent $taskConfig.client_executable)
$taskSettings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName 'YIXIAOER_CLIENT_ADMINISTRATOR_LOGON' -Action $clientAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description '蚁小二正常随Administrator交互登录启动；不绕过登录，不使用SYSTEM。' -Force | Out-Null
$taskArgs='-X utf8 -B -m yixiaoer_adapter.worker --config "'+(Join-Path $taskRoot 'yixiaoer_adapter\worker.config.json')+'"'
$workerAction=New-ScheduledTaskAction -Execute $taskConfig.pythonw -Argument $taskArgs -WorkingDirectory $taskRoot
Register-ScheduledTask -TaskName 'YIXIAOER_PUBLISH_WORKER_SERVER_01' -Action $workerAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description '仅用户Confirm后的3条灰度Plan；默认执行关闭，不消费历史正式队列。' -Force | Out-Null
Get-ScheduledTask -TaskName 'YIXIAOER_CLIENT_ADMINISTRATOR_LOGON','YIXIAOER_PUBLISH_WORKER_SERVER_01' | Select-Object TaskName,State,@{n='UserId';e={$_.Principal.UserId}},@{n='LogonType';e={$_.Principal.LogonType}}
