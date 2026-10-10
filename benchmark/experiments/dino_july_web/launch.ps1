param(
    [ValidateRange(1, 65535)][int]$Port = 8502,
    [switch]$Lan,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$python = Join-Path $projectRoot '.venv-cuda-test/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Missing existing .venv-cuda-test interpreter. See README.md.'
}
$bindAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$serviceArgs = @('-X', 'utf8', '-B', '-m', 'streamlit', 'run',
    (Join-Path $PSScriptRoot 'server.py'), '--server.address', $bindAddress,
    '--server.port', "$Port", '--server.headless', 'true',
    '--browser.gatherUsageStats', 'false', '--server.fileWatcherType', 'none')
# 检查模式只返回启动参数，不停止已有服务、不加载模型。
if ($CheckOnly) {
    [PSCustomObject]@{Python=$python; Address=$bindAddress; Port=$Port; Arguments=$serviceArgs} | ConvertTo-Json
    exit 0
}
$deps = Join-Path $projectRoot 'benchmark/experiments/embedding_comparison/deps'
$pathItems = @($deps, $PSScriptRoot, $projectRoot)
if ($env:PYTHONPATH) { $pathItems += $env:PYTHONPATH }
$env:PYTHONPATH = $pathItems -join [IO.Path]::PathSeparator
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
# 依赖及当前上传预检必须在停止8502之前完成。
Write-Host 'Checking XunFrame Python and DINO dependencies...'
& $python -X utf8 -B (Join-Path $PSScriptRoot 'web_env_check.py')
if ($LASTEXITCODE -ne 0) { throw 'XunFrame environment check failed; existing Web service preserved.' }
if ($Port -eq 8502) {
    & $python -X utf8 -B -c "import sqlite3,sys; from pathlib import Path; p=Path('production_materials/runtime/catalog.sqlite').resolve(); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True); n=c.execute('SELECT count(*) FROM uploads WHERE state NOT IN (?,?,?)',('LIBRARY_READY','DUPLICATE_SKIPPED','QUARANTINED')).fetchone()[0]; c.close(); sys.exit(1 if n else 0)"
    if ($LASTEXITCODE -ne 0) { throw 'Unfinished uploads exist; existing 8502 preserved.' }
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Sort-Object OwningProcess -Unique)
foreach ($listener in $listeners) {
    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = if ($null -ne $processInfo) { [string]$processInfo.CommandLine } else { '' }
    $isXunFrame = $null -ne $process -and $process.ProcessName -in @('python','pythonw') -and
        $commandLine.Contains('streamlit') -and $commandLine.Contains('dino_july_web') -and
        ($commandLine.Contains((Join-Path $PSScriptRoot 'app.py')) -or $commandLine.Contains((Join-Path $PSScriptRoot 'server.py'))) -and
        $commandLine.Contains("--server.port $Port")
    if (-not $isXunFrame) {
        throw "Port $Port is occupied by another program; refusing to stop it."
    }
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Milliseconds 500
}
Write-Host "Local URL: http://127.0.0.1:$Port"
if ($Lan) {
    Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | ForEach-Object {
        foreach ($address in $_.IPv4Address.IPAddress) {
            Write-Host "LAN URL: http://${address}:$Port"
        }
    }
    Write-Host 'LAN access requires the scoped firewall rule. See LAN_ACCESS.md.'
}
& $python @serviceArgs
exit $LASTEXITCODE
