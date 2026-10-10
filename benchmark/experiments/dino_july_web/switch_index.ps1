param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('july_test', 'formal_v1', 'formal_v1_repaired')]
    [string]$Index,
    [int]$Port = 8502
)
$ErrorActionPreference = 'Stop'
$config = Join-Path $PSScriptRoot 'search_config.json'
$temporary = "$config.tmp"
$options = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
$options.search_index = $Index
$options | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $config -Force
Write-Host "寻帧搜索库已切换为 $Index，正在重启服务..."
& (Join-Path $PSScriptRoot 'launch.ps1') -Port $Port
exit $LASTEXITCODE
