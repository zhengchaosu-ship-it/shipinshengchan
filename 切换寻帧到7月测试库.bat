@echo off
chcp 65001 >nul
title 寻帧 - 切换到7月测试库
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0benchmark\experiments\dino_july_web\switch_index.ps1" -Index july_test
pause
