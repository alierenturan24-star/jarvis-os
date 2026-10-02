@echo off
setlocal EnableExtensions EnableDelayedExpansion
title JARVIS Video Surumunu Kur ve Ac - CANLI
color 0B

set "TARGET_BRANCH=codex/youtube-planning-gemini-images"
set "SOURCE_REPO=%JARVIS_SOURCE_REPO%"
if not defined SOURCE_REPO set "SOURCE_REPO=C:\Projects\jarvis-os\jarvis-os"
if not exist "%SOURCE_REPO%\.git" set "SOURCE_REPO=C:\Projects\jarvis-os"

echo ============================================================
echo   JARVIS YENI SURUM - GUVENLI AYRI KURULUM
echo ============================================================
echo.

if not exist "%SOURCE_REPO%\.git" (
  echo JARVIS repo klasoru otomatik bulunamadi.
  echo Ornek: C:\Projects\jarvis-os\jarvis-os
  set /p "SOURCE_REPO=Repo klasorunun tam yolunu yazin: "
)

if not exist "%SOURCE_REPO%\.git" (
  echo.
  echo HATA: Secilen klasorde .git bulunamadi.
  goto :HATA
)

cd /d "%SOURCE_REPO%"
echo [1/4] GitHub'daki yeni surum kontrol ediliyor...
git fetch --progress origin "+refs/heads/%TARGET_BRANCH%:refs/remotes/origin/%TARGET_BRANCH%"
if errorlevel 1 goto :HATA

git show-ref --verify --quiet "refs/remotes/origin/%TARGET_BRANCH%"
if errorlevel 1 (
  echo HATA: Yeni surum GitHub'dan indirilemedi.
  goto :HATA
)

set "INSTALL_ROOT=C:\Projects"
if not exist "%INSTALL_ROOT%" mkdir "%INSTALL_ROOT%"
for /f %%H in ('git rev-parse "refs/remotes/origin/%TARGET_BRANCH%"') do set "REMOTE_HEAD=%%H"
for /f %%H in ('git rev-parse --short^=12 "refs/remotes/origin/%TARGET_BRANCH%"') do set "SHORT_HEAD=%%H"
if not defined REMOTE_HEAD goto :HATA
set "NEW_REPO=%INSTALL_ROOT%\jarvis-active-%SHORT_HEAD%"

echo.
echo [2/4] Eski projeye dokunmadan yeni klasor olusturuluyor...
echo Yeni klasor: %NEW_REPO%
if exist "%NEW_REPO%\.git" (
  for /f %%H in ('git -C "%NEW_REPO%" rev-parse HEAD') do set "EXISTING_HEAD=%%H"
  if /I not "!EXISTING_HEAD!"=="!REMOTE_HEAD!" (
    echo HATA: Mevcut aktif klasor beklenen surumde degil.
    goto :HATA
  )
) else (
  git worktree add --detach "%NEW_REPO%" "refs/remotes/origin/%TARGET_BRANCH%"
  if errorlevel 1 goto :HATA
)

if exist "%SOURCE_REPO%\.env" (
  echo.
  echo [3/4] Yerel API ayarlari yeni surume kopyalaniyor...
  copy /Y "%SOURCE_REPO%\.env" "%NEW_REPO%\.env" >nul
  if errorlevel 1 goto :HATA
) else (
  echo.
  echo [3/4] Eski projede .env bulunamadi; yeni surum ilk acilista olusturacak.
)

if not exist "%NEW_REPO%\START_JARVIS.bat" (
  echo HATA: START_JARVIS.bat yeni surumde bulunamadi.
  goto :HATA
)

echo.
echo [4/4] Yeni JARVIS baslatiliyor...
echo Bu ilk acilissa gerekli paketlerin kurulmasi birkac dakika surebilir.
echo Pencereyi kapatmayin; panel hazir olunca tarayici otomatik acilacak.
echo.
if "%JARVIS_CI%"=="1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEW_REPO%\tools\setup_and_start.ps1" -SetupOnly
) else (
  call "%NEW_REPO%\START_JARVIS.bat"
)
if errorlevel 1 goto :HATA

echo.
echo ============================================================
echo JARVIS HAZIR
echo Kurulum klasoru: %NEW_REPO%
echo Bundan sonra masaustundeki JARVIS AC kisayolunu kullanin.
echo Eski proje ve degisiklikleriniz aynen korundu.
echo ============================================================
if "%JARVIS_CI%"=="1" exit /b 0
pause
exit /b 0

:HATA
echo.
echo ============================================================
echo ISLEM DURDU - ESKI PROJE SILINMEDI VE DEGISTIRILMEDI
echo Yukaridaki son hata satirinin fotografini gonderebilirsiniz.
echo ============================================================
pause
exit /b 1
