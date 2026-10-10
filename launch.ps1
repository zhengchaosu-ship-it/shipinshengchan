param(
    [switch]$CheckOnly,
    [switch]$CheckDependencies,
    [int]$Port = 8501
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

function Resolve-ProjectPath([string]$Value) {
    $expanded = [Environment]::ExpandEnvironmentVariables($Value)
    if ($expanded -eq '~' -or $expanded.StartsWith('~/') -or $expanded.StartsWith('~\')) {
        $expanded = Join-Path ([Environment]::GetFolderPath('UserProfile')) $expanded.Substring(1).TrimStart('\', '/')
    }
    if (-not [IO.Path]::IsPathRooted($expanded)) { $expanded = Join-Path $projectRoot $expanded }
    return [IO.Path]::GetFullPath($expanded)
}

$settingsPath = if ($env:VIDEO_SEARCH_CONFIG) { Resolve-ProjectPath $env:VIDEO_SEARCH_CONFIG } else { Join-Path $projectRoot 'config.json' }
$settings = if (Test-Path -LiteralPath $settingsPath) { Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$pythonPath = $null
$pythonPrefix = @()
if ($settings -and $settings.paths.python_executable) {
    $pythonPath = Resolve-ProjectPath $settings.paths.python_executable
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Configured Python executable does not exist: $pythonPath"
    }
} else {
    $pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonPath = $pythonCommand.Source }
    else {
        $pyCommand = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
        if ($pyCommand) { $pythonPath = $pyCommand.Source; $pythonPrefix = @('-3') }
        else { throw 'Set paths.python_executable in config.json, or add Python to PATH.' }
    }
}

$entry = Join-Path $projectRoot 'video_search.py'
$serviceArgs = $pythonPrefix + @('-B', '-m', 'streamlit', 'run', $entry, '--server.headless', 'true', '--server.port', "$Port")
if ($CheckOnly) {
    [PSCustomObject]@{Python=$pythonPath; Config=$settingsPath; WorkingDirectory=$projectRoot; Arguments=$serviceArgs} | ConvertTo-Json
    exit 0
}

Push-Location -LiteralPath $projectRoot
try {
    if ($CheckDependencies) {
        & $pythonPath @pythonPrefix -B -c 'import streamlit, cv2, torch, faiss, faster_whisper, rapidocr_onnxruntime'
        if ($LASTEXITCODE -ne 0) {
            & $pythonPath @pythonPrefix -m pip install -r (Join-Path $projectRoot 'requirements.txt') -i 'https://mirrors.huaweicloud.com/repository/pypi/simple/'
            if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
        }
    }
    & $pythonPath @serviceArgs
    $serviceExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $serviceExitCode
