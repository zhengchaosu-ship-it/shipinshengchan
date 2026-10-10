$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskConfigPath = Join-Path $PSScriptRoot 'resident_monitor.config.json'
$taskMonitorConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
if ($taskMonitorConfig.mode -ne 'MONITOR_ONLY' -or $taskMonitorConfig.real_publish_enabled -ne $false) {
    throw 'RESIDENT_EXECUTION_NOT_IMPLEMENTED_MONITOR_ONLY'
}
$taskPython = (Get-Content -LiteralPath (Join-Path $taskProjectRoot 'config.json') -Raw | ConvertFrom-Json).paths.python_executable
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-X', 'utf8', '-m', 'xiaovcat_adapter.desktop_worker.resident_monitor', '--config', $taskConfigPath) -WorkingDirectory $taskProjectRoot -WindowStyle Hidden -Wait -PassThru
exit $taskProcess.ExitCode
