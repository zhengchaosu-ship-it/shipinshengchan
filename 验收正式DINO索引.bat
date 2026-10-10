@echo off
setlocal
cd /d "%~dp0"
set CUDA_VISIBLE_DEVICES=
"%~dp0.venv-cuda-test\Scripts\python.exe" -X utf8 -B "%~dp0dino_index\validate_formal.py"
set "VALIDATION_EXIT=%ERRORLEVEL%"
echo.
if "%VALIDATION_EXIT%"=="0" (
    echo 验收完成：READY
) else (
    echo 验收未通过，退出码 %VALIDATION_EXIT%
)
pause
exit /b %VALIDATION_EXIT%
