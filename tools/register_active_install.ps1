param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$startFile = Join-Path $resolvedRoot 'START_JARVIS.bat'
if (-not (Test-Path -LiteralPath $startFile -PathType Leaf)) {
    throw "START_JARVIS.bat bulunamadi: $resolvedRoot"
}

$projectsRoot = 'C:\Projects'
New-Item -ItemType Directory -Force -Path $projectsRoot | Out-Null
$pointerPath = Join-Path $projectsRoot 'JARVIS_ACTIVE_PATH.txt'
$launcherPath = Join-Path $projectsRoot 'JARVIS_AC.bat'
Set-Content -LiteralPath $pointerPath -Value $resolvedRoot -Encoding ascii

$launcher = @'
@echo off
setlocal
title JARVIS AC
set "POINTER=C:\Projects\JARVIS_ACTIVE_PATH.txt"
if not exist "%POINTER%" goto :missing
set /p "JARVIS_ROOT="<"%POINTER%"
if not exist "%JARVIS_ROOT%\tools\update_active_install.ps1" goto :missing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_ROOT%\tools\update_active_install.ps1"
if not errorlevel 1 exit /b 0
echo.
echo Guncelleme acilamadi. Calisan mevcut JARVIS surumu aciliyor...
if not exist "%JARVIS_ROOT%\START_JARVIS.bat" goto :missing
call "%JARVIS_ROOT%\START_JARVIS.bat"
if not errorlevel 1 exit /b 0
echo.
echo JARVIS baslatilamadi. Bu pencere hata gorulebilsin diye acik tutuluyor.
pause
exit /b 1
:missing
echo JARVIS aktif kurulum yolu bulunamadi.
echo JARVIS Tamir ve Ac dosyasini bir kez calistirin.
pause
exit /b 1
'@
Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding ascii

$desktop = [Environment]::GetFolderPath('Desktop')
if ($desktop) {
    $shortcutPath = Join-Path $desktop 'JARVIS AC.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $launcherPath
    $shortcut.WorkingDirectory = $projectsRoot
    $shortcut.Description = 'JARVIS guncelle ve Control Center ac'
    $shortcut.Save()
}

Write-Host "      Aktif JARVIS: $resolvedRoot" -ForegroundColor Green
Write-Host "      Bundan sonra masaustundeki JARVIS AC kisayolunu kullanin." -ForegroundColor Green
