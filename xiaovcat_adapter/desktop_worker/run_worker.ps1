param([switch]$LaunchOnly, [switch]$ProbeOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location -LiteralPath $taskRoot
$taskConfig = Get-Content -LiteralPath (Join-Path $taskRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskPython = $taskConfig.paths.python_executable
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Configured Python not found.' }
$env:PYTHONIOENCODING = 'utf-8'
$taskArgs = @('-m', 'xiaovcat_adapter.desktop_worker.worker')
if ($LaunchOnly) { $taskArgs += '--launch-only' }
if ($ProbeOnly) { $taskArgs += '--probe-only' }
& $taskPython @taskArgs
exit $LASTEXITCODE
