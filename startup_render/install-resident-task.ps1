param([Parameter(Mandatory=$true)][ValidateSet('server','worker')][string]$Role,
      [Parameter(Mandatory=$true)][string]$Python,
      [Parameter(Mandatory=$true)][string]$Config,
      [Parameter(Mandatory=$true)][string]$Project)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($Project)
$pythonPath=(Resolve-Path -LiteralPath $Python).Path
$configPath=(Resolve-Path -LiteralPath $Config).Path
if([IO.Path]::GetFileName($pythonPath) -ne 'pythonw.exe'){throw 'USE_HIDDEN_PYTHONW'}
$module=if($Role -eq 'worker'){'startup_render.render_worker'}else{'startup_render.lan_server'}
$taskName=if($Role -eq 'worker'){'XUNZHEN_RENDER_WORKER'}else{'XunZhen-Startup-Render-server'}
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute $pythonPath -Argument ('-X utf8 -B -m '+$module+' --config "'+$configPath+'"') -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -Hidden -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($existing -and $existing.State -eq 'Running'){throw 'TASK_RUNNING_NO_REPLACE'}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -Description 'LAN resident Render only. HTTP JSON + authenticated SMB. NO publishing.' | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State,@{n='User';e={$_.Principal.UserId}},@{n='LogonType';e={$_.Principal.LogonType}}
