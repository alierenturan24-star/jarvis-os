@echo off
setlocal EnableExtensions EnableDelayedExpansion
title JARVIS Video Surumunu Kur ve Ac
set "LOG=%TEMP%\JARVIS_VIDEO_KURULUM_LOGU.txt"

call :KUR >"%LOG%" 2>&1
set "SONUC=%ERRORLEVEL%"
cls
type "%LOG%"
echo.
if "%SONUC%"=="0" (
  echo JARVIS BASLATILDI. Bu pencereyi kapatabilirsiniz.
) else (
  echo KURULUM TAMAMLANAMADI.
  echo Hata kaydi: %LOG%
)
echo.
pause
exit /b %SONUC%

:KUR
set "TARGET_BRANCH=codex/youtube-planning-gemini-images"
set "REPO=C:\Projects\jarvis-os\jarvis-os"
if not exist "%REPO%\.git" set "REPO=C:\Projects\jarvis-os"

if not exist "%REPO%\.git" (
  echo JARVIS repo klasoru otomatik bulunamadi.
  echo Ornek: C:\Projects\jarvis-os\jarvis-os
  set /p "REPO=Repo klasorunun tam yolunu yazin: "
)

if not exist "%REPO%\.git" (
  echo HATA: Secilen klasorde .git bulunamadi.
  exit /b 1
)

cd /d "%REPO%"
for /f %%B in ('git branch --show-current') do set "ORIGINAL_BRANCH=%%B"
for /f %%H in ('git rev-parse HEAD') do set "ORIGINAL_HEAD=%%H"
for /f %%H in ('git rev-parse --short HEAD') do set "SHORT_HEAD=%%H"
if not defined ORIGINAL_HEAD (
  echo HATA: Git deposunun mevcut surumu okunamadi.
  exit /b 1
)
set "BACKUP_BRANCH=backup/jarvis-before-video-!SHORT_HEAD!-%RANDOM%"
set "RUN_BRANCH=jarvis-video-ready-%RANDOM%"

echo [1/4] Mevcut surum guvenli dala aliniyor...
git branch "!BACKUP_BRANCH!" "!ORIGINAL_HEAD!"
if errorlevel 1 exit /b 1
echo Guvenlik dali: !BACKUP_BRANCH!

set "HAS_CHANGES=0"
for /f "delims=" %%S in ('git status --porcelain') do set "HAS_CHANGES=1"
if "!HAS_CHANGES!"=="1" (
  echo Yerel degisiklikler gecici kasaya aliniyor...
  git stash push --include-untracked -m "jarvis-video-safe-update-!SHORT_HEAD!"
  if errorlevel 1 exit /b 1
  set "STASHED=1"
)

echo [2/4] Hazir video surumu GitHub'dan aliniyor...
git fetch origin "+refs/heads/!TARGET_BRANCH!:refs/remotes/origin/!TARGET_BRANCH!"
if errorlevel 1 goto :GERI_DON

git show-ref --verify --quiet "refs/remotes/origin/!TARGET_BRANCH!"
if errorlevel 1 (
  echo HATA: GitHub dali bilgisayara indirilemedi.
  goto :GERI_DON
)

echo [3/4] Yeni surum ayri bir dalda aciliyor...
git switch --create "!RUN_BRANCH!" "refs/remotes/origin/!TARGET_BRANCH!"
if errorlevel 1 goto :GERI_DON

if not exist "%REPO%\START_JARVIS.bat" (
  echo HATA: START_JARVIS.bat bulunamadi.
  goto :GERI_DON
)

echo [4/4] JARVIS baslatiliyor...
echo Calisan dal: !RUN_BRANCH!
if defined STASHED echo Not: Eski yerel degisiklikleriniz git stash icinde korundu.
start "JARVIS" "%REPO%\START_JARVIS.bat"
if errorlevel 1 goto :GERI_DON
exit /b 0

:GERI_DON
echo Yeni surum acilamadi; onceki dala donuluyor...
if defined ORIGINAL_BRANCH git switch "!ORIGINAL_BRANCH!" >nul 2>&1
if defined STASHED git stash pop
echo Mevcut commitleriniz silinmedi.
if defined BACKUP_BRANCH echo Guvenlik dali: !BACKUP_BRANCH!
exit /b 1
