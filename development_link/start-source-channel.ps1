$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskRoot '.venv-cuda-test/Scripts/python.exe'
$taskPythonHidden = Join-Path $taskRoot '.venv-cuda-test/Scripts/pythonw.exe'
$taskFirewallProgram = (& $taskPython -c "from pathlib import Path; import sys; print(Path(sys._base_executable).with_name('pythonw.exe'))").Trim()
if (-not (Test-Path -LiteralPath $taskFirewallProgram)) { throw 'Actual hidden Python interpreter not found.' }
if (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue) {
    throw '8765 already in use; inspect it first. No process will be stopped.'
}
$taskRule = 'XunZhen-Source-Git-2060S-8765'
if (-not (Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name $taskRule -DisplayName $taskRule -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -LocalAddress 192.168.1.126 -RemoteAddress 192.168.1.89 -Program $taskFirewallProgram -Profile Any -EdgeTraversalPolicy Block | Out-Null
} else {
    Get-NetFirewallRule -Name $taskRule | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program $taskFirewallProgram | Out-Null
}
# 使用当前用户的系统任务独立运行，只读源码进程不依赖Codex会话生命周期。
# 不保存密码、不使用SYSTEM、不涉及任何真实发布或线上工作台重启。
$taskName = 'XunZhen-Source-Git-2060S'
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskArgs = '-X utf8 -B "' + (Join-Path $PSScriptRoot 'serve_git.py') + '"'
$taskExisting = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($taskExisting) {
    if ($taskExisting.Actions.Execute -ne $taskPythonHidden -or $taskExisting.Actions.Arguments -ne $taskArgs) {
        throw 'Existing task differs; refusing to overwrite it.'
    }
} else {
    $taskAction = New-ScheduledTaskAction -Execute $taskPythonHidden -Argument $taskArgs -WorkingDirectory $taskRoot
    $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -Hidden -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description 'Read-only vetted XunZhen source for 192.168.1.89; no publishing or workbench restart.' | Out-Null
}
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
