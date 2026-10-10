# 只由服务器Administrator本人执行。固定原Job3，不接收任务参数。
$ErrorActionPreference = 'Stop'
Write-Output 'JOB_CANCELLED'
exit 20
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if ($args.Count -ne 0) { throw 'JOB3_ONLY_NO_ARGUMENTS' }
$publishProjectRoot = 'D:\video_search_tool'
$publishPython = 'C:\Users\Administrator\AppData\Local\Doubao\User Data\sandbox_runtime\bases\c98c5042338ed152c6f10ecd8591889f\python\python.exe'
$publishTarget = 'D:\video_search_tool\xiaovcat_adapter\server_job3_real_once.py'
$publishPaths = @(
    $publishProjectRoot,
    $publishPython,
    $publishTarget,
    'D:\video_search_tool\operations.db',
    'D:\小V猫\小V猫.exe',
    'D:\video_search_tool\outputs\startup_exports\STARTUP_b681bc5228bb43018cdfb6d4556a7af4\丙曜起号10月4日-6.mp4'
)
foreach ($publishPath in $publishPaths) {
    if (!(Test-Path -LiteralPath $publishPath)) { throw 'JOB3_REAL_ONCE_PATH_NOT_FOUND' }
}
$publishConfiguredPython = (Get-Content -LiteralPath 'D:\video_search_tool\config.json' -Raw -Encoding UTF8 | ConvertFrom-Json).paths.python_executable
if ([IO.Path]::GetFullPath($publishConfiguredPython) -ne [IO.Path]::GetFullPath($publishPython)) {
    throw 'PYTHON_INTERPRETER_MISMATCH'
}
Set-Location -LiteralPath $publishProjectRoot
& $publishPython -X utf8 -B -m xiaovcat_adapter.server_job3_real_once
exit $LASTEXITCODE
