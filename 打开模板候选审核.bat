@echo off
cd /d "%~dp0"
start "Template Review" http://127.0.0.1:8503/report.html
"%~dp0.venv-cuda-test\Scripts\python.exe" -X utf8 -B -m template_editing.serve --port 8503
pause
