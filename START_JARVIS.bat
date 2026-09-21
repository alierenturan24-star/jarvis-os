@echo off
setlocal
cd /d "%~dp0"
title JARVIS Kurulum ve Baslatma

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup_and_start.ps1"
if errorlevel 1 (
  echo.
  echo JARVIS baslatilamadi. Yukaridaki mesaji kontrol edin.
  pause
)

endlocal
