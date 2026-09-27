@echo off
setlocal
cd /d "%~dp0"
title JARVIS Guncelle ve Baslat

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\update_and_start.ps1"
if errorlevel 1 (
  echo.
  echo JARVIS guncellenemedi veya baslatilamadi. Yukaridaki mesaji kontrol edin.
  pause
)

endlocal
