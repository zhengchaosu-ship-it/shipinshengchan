param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv-cuda-test\Scripts\pythonw.exe'
$pythonConsole = Join-Path $projectRoot '.venv-cuda-test\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot 'service.config.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$taskName = 'XunZhen-ProductionMaterialUpload-8510'
$taskArgs = '-X utf8 -B -m production_materials.service --config "' + $configPath + '"'
$current = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($current -and ($current.Actions.Arguments -ne $taskArgs -or $current.Actions.Execute -ne $pythonPath)){throw 'Existing task has an unexpected action.'}
$wasRunning = $current -and $current.State -eq 'Running'
if($current -and $current.State -eq 'Running'){
    if($Restart){
        # 仅本服务升级；未完成上传保留时禁止强停。
        & $pythonConsole -X utf8 -B -c "import sqlite3,sys; from pathlib import Path; from production_materials.config import settings; p=Path(settings()['database']); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); n=c.execute('SELECT count(*) FROM uploads WHERE state NOT IN (?,?,?)',('LIBRARY_READY','DUPLICATE_SKIPPED','QUARANTINED')).fetchone()[0]; c.close(); sys.exit(1 if n else 0)"
        if($LASTEXITCODE -ne 0){throw 'Unfinished uploads exist; refusing to restart material service.'}
        Stop-ScheduledTask -TaskName $taskName
        for($attempt=0;$attempt -lt 10;$attempt++){
            if((Get-ScheduledTask -TaskName $taskName).State -ne 'Running'){break}
            Start-Sleep -Milliseconds 500
        }
        if((Get-ScheduledTask -TaskName $taskName).State -eq 'Running'){throw 'Material task did not stop; refusing second instance.'}
        $wasRunning = $false
    }
}
$taskAction = New-ScheduledTaskAction -Execute $pythonPath -Argument $taskArgs -WorkingDirectory $projectRoot
$taskTrigger = New-ScheduledTaskTrigger -AtStartup
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$taskPrincipal = New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN + '\' + $env:USERNAME) -LogonType S4U -RunLevel Limited
if($wasRunning){
    Set-ScheduledTask -TaskName $taskName -Settings $taskSettings | Out-Null
}else{
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Principal $taskPrincipal -Description 'LAN-only production material upload. No render, provider or publish calls.' -Force | Out-Null
}
# venv启动器会派生基础pythonw；防火墙必须匹配实际监听程序。
$baseExecutable = & $pythonConsole -X utf8 -B -c "import sys; print(sys._base_executable)"
if($LASTEXITCODE -ne 0){throw 'Cannot resolve actual Python runtime.'}
$listenerExecutable = Join-Path (Split-Path -Parent $baseExecutable.Trim()) 'pythonw.exe'
if(-not (Test-Path -LiteralPath $listenerExecutable -PathType Leaf)){throw 'Actual Python listener executable is missing.'}
$firewallName='XunZhen-ProductionMaterialUpload-LAN-8510'
if(Get-NetFirewallRule -Name $firewallName -ErrorAction SilentlyContinue){
    Set-NetFirewallRule -Name $firewallName -Program $listenerExecutable | Out-Null
}else{
    New-NetFirewallRule -Name $firewallName -DisplayName $firewallName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $config.port -LocalAddress '192.168.1.126' -RemoteAddress '192.168.1.0/24' -Program $listenerExecutable -Profile Any | Out-Null
}
$guardName = 'XunZhen-ProductionMaterialUpload-Watchdog'
$guardAction = New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -B -m production_materials.watchdog' -WorkingDirectory $projectRoot
$guardTriggers = @((New-ScheduledTaskTrigger -AtStartup),(New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)))
$guardSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)
$guardPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $guardName -Action $guardAction -Trigger $guardTriggers -Settings $guardSettings -Principal $guardPrincipal -Description 'Recover only exited original material upload task; bounded restart budget; no worker or production job operations.' -Force | Out-Null
if(-not $wasRunning){Start-ScheduledTask -TaskName $taskName}
Start-ScheduledTask -TaskName $guardName
Write-Output 'Material upload task and minute watchdog configured; LAN listener rule repaired. Existing running upload service preserved.'
