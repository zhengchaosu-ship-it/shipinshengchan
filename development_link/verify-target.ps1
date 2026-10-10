$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($taskRoot -ne 'D:\Projects\XunZhen') { throw '2060S checkout only; do not run on production server.' }
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv-dev/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create the independent .venv-dev first.' }
$taskTemplates = @(
    @('development_link/config.example.json','config.json'),
    @('development_link/xiaovcat.config.example.json','xiaovcat_adapter/config.json'),
    @('development_link/search_config.example.json','benchmark/experiments/dino_july_web/search_config.json'),
    @('development_link/jianying.config.example.json','jianying_auto/config.json'),
    @('development_link/jianying_source_folders.example.json','jianying_auto/jianying_source_folders.json')
)
foreach ($taskPair in $taskTemplates) {
    if (-not (Test-Path -LiteralPath $taskPair[1])) {
        Copy-Item -LiteralPath $taskPair[0] -Destination $taskPair[1]
    }
}
$taskConfig = Get-Content xiaovcat_adapter/config.json -Raw -Encoding UTF8 | ConvertFrom-Json
if ($taskConfig.real_publish_enabled -ne $false) { throw 'Real publish must remain disabled.' }
New-Item -ItemType Directory -Path 'development_link/verification' -Force | Out-Null
# Windows PowerShell 5将原生程序stderr变成ErrorRecord；pip提示不等于失败。
# 以真实进程退出码判断，保留stdout/stderr证据。
$ErrorActionPreference = 'Continue'
& $taskPython -m pip install -r development_link/requirements-dev.txt -c requirements.txt *> development_link/verification/pip-install.log
$taskExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($taskExit -ne 0) { throw 'Dependency install failed; see verification/pip-install.log.' }
$ErrorActionPreference = 'Continue'
& $taskPython -m pip check *> development_link/verification/pip-check.log
$taskExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($taskExit -ne 0) { throw 'Dependency check failed.' }
& $taskPython -X utf8 (Join-Path $PSScriptRoot 'initialize-dev-db.py')
if ($LASTEXITCODE -ne 0) { throw 'Isolated development database initialization failed.' }
# 只运行项目现有的隔离测试入口，不调度Worker，不加载生产索引或素材。
$ErrorActionPreference = 'Continue'
& $taskPython -X utf8 -m startup_pipeline.verify *> development_link/verification/regression.log
$taskExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($taskExit -ne 0) { throw 'Existing regression failed; no business code was changed to hide failure.' }
Get-Content xiaovcat_adapter/results/startup_pipeline_v01/TEST_RESULTS.json -Raw -Encoding UTF8
