$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($taskRoot -ne 'D:\Projects\XunZhen') { throw 'This script is for the 2060S checkout only.' }
Set-Location -LiteralPath $taskRoot
if (git status --porcelain --untracked-files=all) { throw 'Save your development changes before updating. Nothing was overwritten.' }
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed.' }
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'Branches diverged. Review manually; no reset or force merge performed.' }
