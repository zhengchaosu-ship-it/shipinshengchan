$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$project='D:\video_search_tool'
$runtime=Join-Path $project 'xiaovcat_adapter\runtime\lan_publish_2060s'
$outputShare=(Get-SmbShare -Name RenderOutput).Path
$packageShare=(Get-SmbShare -Name StartupTaskFiles).Path
if ($outputShare -ne 'D:\video_search_tool\outputs\lan_render') { throw 'UNEXPECTED_RENDER_OUTPUT_SHARE' }
if (-not (Test-Path -LiteralPath $packageShare)) { throw 'EXISTING_PACKAGE_SHARE_REQUIRED' }
$source=Join-Path $project 'outputs\startup_exports\STARTUP_b681bc5228bb43018cdfb6d4556a7af4\丙曜起号10月4日-6.mp4'
$expected='8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256'
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower() -ne $expected) { throw 'SOURCE_HASH_MISMATCH' }
$target=Join-Path $outputShare 'publish_jobs\af6c16d3-2912-4390-88c7-4584b3e4feea\video\丙曜起号10月4日-6.mp4'
if (-not (Test-Path -LiteralPath $target)) {
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $target
}
if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -ne $expected) { throw 'SMB_STAGE_HASH_MISMATCH_NO_OVERWRITE' }
$transfer=Join-Path $packageShare 'PublishRuntime2060S'
New-Item -ItemType Directory -Path $transfer -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $runtime 'worker_runtime.zip') -Destination $transfer
Copy-Item -LiteralPath (Join-Path $project 'xiaovcat_adapter\deployment\deploy_2060s.ps1') -Destination $transfer
# 已有Render文件只部署经验证的GUI互斥包装；不启动/重启Render。
Copy-Item -LiteralPath (Join-Path $project 'startup_render\agent.py') -Destination (Join-Path $transfer 'agent.py')
Copy-Item -LiteralPath (Join-Path $project 'startup_render\agent.py.publish-ui-lane-20261005.bak') -Destination (Join-Path $transfer 'agent.previous.py')
$python=(Get-Content (Join-Path $project 'config.json') -Raw | ConvertFrom-Json).paths.python_executable
$pythonw=Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'EXISTING_PYTHONW_REQUIRED' }
$taskName='XUNZHEN_PUBLISH_DISPATCH_API'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'API_TASK_ALREADY_EXISTS_NO_OVERWRITE' }
if (Get-NetTCPConnection -State Listen -LocalPort 8776 -ErrorAction SilentlyContinue) { throw 'PUBLISH_API_PORT_BUSY' }
$action=New-ScheduledTaskAction -Execute $pythonw -Argument '-X utf8 -B -m xiaovcat_adapter.lan_publish_server --config "D:\video_search_tool\xiaovcat_adapter\deployment\server.lan.json"' -WorkingDirectory $project
$trigger=New-ScheduledTaskTrigger -AtLogOn -User 'PC-20260617GEOP\Administrator'
$principal=New-ScheduledTaskPrincipal -UserId 'PC-20260617GEOP\Administrator' -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'LAN production repository only; no desktop automation' | Out-Null
$ruleName='XUNZHEN_PUBLISH_API_8776_2060S'
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) { throw 'FIREWALL_RULE_ALREADY_EXISTS_VERIFY_MANUALLY' }
New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8776 -LocalAddress 192.168.1.126 -RemoteAddress 192.168.1.89 -Profile Private | Out-Null
Start-ScheduledTask -TaskName $taskName
[pscustomobject]@{task=$taskName;staged_video=$target;sha256=$expected;package_share=$transfer;package_sha256=(Get-FileHash (Join-Path $transfer 'worker_runtime.zip') -Algorithm SHA256).Hash} | ConvertTo-Json
