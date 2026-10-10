@echo off
chcp 65001 >nul
title 寻帧 - 切换到正式素材库
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0benchmark\experiments\dino_july_web\switch_index.ps1" -Index formal_v1_repaired
pause
