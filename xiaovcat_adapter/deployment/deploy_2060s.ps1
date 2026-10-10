$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
if ([System.Net.Dns]::GetHostName() -ne 'DESKTOP-9VQ76D3') { throw '2060S_ONLY' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.User.Value -ne 'S-1-5-21-1134442622-1985318965-2583428394-1001') { throw 'SDAFFWS_USER_REQUIRED' }
$root='D:\XunZhenPublishWorker'
$source='\\PC-20260617GEOP\StartupTaskFiles\PublishRuntime2060S'
if (Test-Path -LiteralPath $root) { throw 'TARGET_EXISTS_NO_OVERWRITE' }
if (Get-ScheduledTask -TaskName 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER' -ErrorAction SilentlyContinue) { throw 'PUBLISH_TASK_EXISTS_NO_OVERWRITE' }
$oldAgent='D:\Projects\XunZhen\startup_render\agent.py'
if ((Get-FileHash -LiteralPath $oldAgent -Algorithm SHA256).Hash -ne '24AA241213E78C84329C6DF65F67B4F2FC3892C7E2CCABD772270D74BCB1F39F') { throw 'RENDER_SOURCE_DRIFT_NO_OVERWRITE' }
# 已只读逐行比对：两端旧源码仅末尾空行/换行不同，除此无业务差异。
if ((Get-Content -LiteralPath $oldAgent -Raw).TrimEnd() -cne (Get-Content -LiteralPath (Join-Path $source 'agent.previous.py') -Raw).TrimEnd()) { throw 'RENDER_SOURCE_DIFF_NO_OVERWRITE' }
$python='D:\JianyingRenderWorker\venv\Scripts\python.exe'
$pythonw='D:\JianyingRenderWorker\venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'EXISTING_RUNTIME_REQUIRED' }
New-Item -ItemType Directory -Path $root | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'worker_runtime.zip') -Destination $root
if ((Get-FileHash -LiteralPath (Join-Path $root 'worker_runtime.zip')).Hash -ne (Get-FileHash -LiteralPath (Join-Path $source 'worker_runtime.zip')).Hash) { throw 'RUNTIME_PACKAGE_SHA_MISMATCH' }
Expand-Archive -LiteralPath (Join-Path $root 'worker_runtime.zip') -DestinationPath $root
if (Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object { $_.Extension -in '.db','.dpapi','.pem','.key' }) { throw 'BUSINESS_DB_OR_SECRET_IN_PACKAGE' }
Copy-Item -LiteralPath $oldAgent -Destination ($oldAgent+'.publish-ui-lane-20261005.bak')
Copy-Item -LiteralPath (Join-Path $source 'agent.py') -Destination $oldAgent
Copy-Item -LiteralPath (Join-Path $root 'xiaovcat_adapter\desktop_ui_lane.py') -Destination 'D:\Projects\XunZhen\xiaovcat_adapter\desktop_ui_lane.py'
# 未武装observer只读取LAN队列/进程元数据并发心跳；没有调用UIA流程。
$publishTaskAction=New-ScheduledTaskAction -Execute $pythonw -Argument '-X utf8 -B "D:\XunZhenPublishWorker\xiaovcat_publish_worker.py" --config "D:\XunZhenPublishWorker\worker.config.json"' -WorkingDirectory $root
$publishTaskTrigger=New-ScheduledTaskTrigger -AtLogOn -User 'DESKTOP-9VQ76D3\sdaffwS'
$publishTaskPrincipal=New-ScheduledTaskPrincipal -UserId 'DESKTOP-9VQ76D3\sdaffwS' -LogonType Interactive -RunLevel Limited
$publishTaskSettings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
if (-not $publishTaskAction -or -not $publishTaskTrigger -or -not $publishTaskPrincipal -or -not $publishTaskSettings) { throw 'SCHEDULED_TASK_DEFINITION_INCOMPLETE' }
Register-ScheduledTask -TaskName 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER' -Action $publishTaskAction -Trigger $publishTaskTrigger -Principal $publishTaskPrincipal -Settings $publishTaskSettings -Description '2060S unarmed LAN observer; UI only in user-operated Job3 entry' | Out-Null
Start-ScheduledTask -TaskName 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER'
[pscustomobject]@{hostname=[System.Net.Dns]::GetHostName();user=$identity.Name;runtime=$root;task='XUNZHEN_XIAOVCAT_PUBLISH_WORKER';mode='NO_UI_NO_CLAIM';package_sha256=(Get-FileHash -LiteralPath (Join-Path $root 'worker_runtime.zip')).Hash} | ConvertTo-Json
