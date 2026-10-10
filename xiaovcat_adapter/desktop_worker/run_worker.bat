@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_worker.ps1" %*
set "WORKER_EXIT=%ERRORLEVEL%"
echo.
echo Worker exit code: %WORKER_EXIT%
pause
exit /b %WORKER_EXIT%
