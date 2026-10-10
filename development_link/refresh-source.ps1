$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskRoot '.venv-cuda-test/Scripts/python.exe'
& $taskPython -X utf8 -B (Join-Path $PSScriptRoot 'export_source.py')
if ($LASTEXITCODE -ne 0) { throw 'Source export failed; no deployment attempted.' }
