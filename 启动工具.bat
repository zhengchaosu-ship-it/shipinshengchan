@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" -CheckDependencies %*
set "tool_exit_code=%errorlevel%"
pause
exit /b %tool_exit_code%
