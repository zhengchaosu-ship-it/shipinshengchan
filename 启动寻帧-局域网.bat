@echo off
chcp 65001 >nul
title 寻帧 - 局域网服务
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0benchmark\experiments\dino_july_web\launch.ps1" -Lan %*
pause
