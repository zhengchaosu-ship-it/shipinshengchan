param([switch]$NoSubmitPreflight)
# 本轮只做启动器预检。没有真实执行授权时，即使漏传参数也安全拒绝。
$ErrorActionPreference = 'Stop'
Write-Output 'JOB_CANCELLED'
exit 20
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if (!$NoSubmitPreflight) { throw 'REAL_EXECUTION_REQUIRES_NEW_AUTHORIZATION' }
$publishProjectRoot = 'D:\video_search_tool'
if (!(Test-Path -LiteralPath $publishProjectRoot -PathType Container)) { throw 'PROJECT_ROOT_NOT_FOUND' }
$publishConfigPath = 'D:\video_search_tool\config.json'
if (!(Test-Path -LiteralPath $publishConfigPath -PathType Leaf)) { throw 'PROJECT_CONFIG_NOT_FOUND' }
$publishPython = (Get-Content -LiteralPath $publishConfigPath -Encoding UTF8 -Raw | ConvertFrom-Json).paths.python_executable
$publishPaths = [ordered]@{
    project_root = $publishProjectRoot
    powershell_executable = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    powershell_wrapper = 'D:\video_search_tool\xiaovcat_adapter\deployment\run_server_job3_user.ps1'
    python_interpreter = $publishPython
    acceptance_script = 'D:\video_search_tool\xiaovcat_adapter\server_resident.py'
    operations_db = 'D:\video_search_tool\operations.db'
    job3_mp4 = 'D:\video_search_tool\outputs\startup_exports\STARTUP_b681bc5228bb43018cdfb6d4556a7af4\丙曜起号10月4日-6.mp4'
}
$publishPathChecks = @($publishPaths.GetEnumerator() | ForEach-Object {
    $publishPathKind = if ($_.Key -eq 'project_root') { 'Container' } else { 'Leaf' }
    [pscustomobject]@{name=$_.Key;path=$_.Value;exists=(Test-Path -LiteralPath $_.Value -PathType $publishPathKind)}
})
$publishPathChecks | ConvertTo-Json -Depth 3
if (@($publishPathChecks | Where-Object { !$_.exists }).Count) { throw 'LAUNCHER_PATH_CHECK_FAILED' }
$publishDiagnosticRoot = 'D:\video_search_tool\xiaovcat_adapter\runtime\server_publish_worker\launcher_preflight'
New-Item -ItemType Directory -Path $publishDiagnosticRoot -Force | Out-Null
$publishPathChecks | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $publishDiagnosticRoot 'TEST_PATH_RESULTS.json') -Encoding UTF8
Set-Location -LiteralPath $publishProjectRoot
& $publishPython -X utf8 -B -m xiaovcat_adapter.server_resident --launcher-preflight-only
exit $LASTEXITCODE
