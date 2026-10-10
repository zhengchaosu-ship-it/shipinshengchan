param(
    [Parameter(Mandatory=$true)][ValidateSet('server','agent')][string]$Role,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Config
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = [IO.Path]::GetFullPath($Python)
$taskConfigPath = (Resolve-Path -LiteralPath $Config).Path
$taskConfig = Get-Content -LiteralPath $taskConfigPath -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Python not found' }
if ([IO.Path]::GetFileName($taskPython) -ne 'pythonw.exe') { throw 'Use hidden pythonw.exe' }
$taskName = 'XunZhen-Startup-Render-' + $Role
$taskArgs = '-X utf8 -B -m startup_render.' + $Role + ' --config "' + $taskConfigPath + '"'
$taskExisting = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($taskExisting) {
    if ($taskExisting.Actions.Execute -ne $taskPython -or $taskExisting.Actions.Arguments -ne $taskArgs) {
        throw 'Existing task differs; refusing to replace'
    }
} else {
    if ($Role -eq 'server') {
        if (Get-NetTCPConnection -State Listen -LocalPort $taskConfig.port -ErrorAction SilentlyContinue) {
            throw 'Server port in use; no process stopped'
        }
        $taskConsole = Join-Path (Split-Path $taskPython) 'python.exe'
        $taskActualPython = (& $taskConsole -c "from pathlib import Path; import sys; print(Path(sys._base_executable).with_name('pythonw.exe'))").Trim()
        $taskRule = 'XunZhen-Startup-Render-2060S-8766'
        if (-not (Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -Name $taskRule -DisplayName $taskRule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $taskConfig.port -LocalAddress $taskConfig.bind -RemoteAddress 192.168.1.89 -Program $taskActualPython -Profile Any -EdgeTraversalPolicy Block | Out-Null
        }
    }
    $taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $taskAction = New-ScheduledTaskAction -Execute $taskPython -Argument $taskArgs -WorkingDirectory $taskRoot
    $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -Hidden -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description 'New startup draft export handoff only; NO publishing and NO stored credentials' | Out-Null
}
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
