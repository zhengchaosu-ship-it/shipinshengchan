param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('true', 'false')]
    [string]$Enabled,
    [int]$Port = 8502,
    [switch]$NoRestart
)
$ErrorActionPreference = 'Stop'
$config = Join-Path $PSScriptRoot 'search_config.json'
$options = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
$options | Add-Member -NotePropertyName candidate_dedup -NotePropertyValue ($Enabled -eq 'true') -Force
$temporary = "$config.tmp"
$options | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $config -Force
Write-Host "candidate_dedup = $Enabled"
if (-not $NoRestart) {
    & (Join-Path $PSScriptRoot 'launch.ps1') -Port $Port
    exit $LASTEXITCODE
}
