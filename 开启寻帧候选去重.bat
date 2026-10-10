@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0benchmark\experiments\dino_july_web\set_candidate_dedup.ps1" -Enabled true
pause
