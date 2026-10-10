$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python = [Environment]::ExpandEnvironmentVariables([string]$config.paths.python_executable)
if (-not [IO.Path]::IsPathRooted($python)) { $python = Join-Path $projectRoot $python }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python不存在：$python" }
$result = Join-Path $projectRoot 'bestseller_analysis\results\batch_20_v1'
if (-not (Test-Path -LiteralPath (Join-Path $result 'BUSINESS_REPORT.md'))) { throw "分析结果不存在：$result" }
Start-Process 'http://127.0.0.1:8504/'
Push-Location -LiteralPath $projectRoot
try {
    & $python -X utf8 -B -m bestseller_analysis.review_server $result --port 8504
} finally {
    Pop-Location
}

