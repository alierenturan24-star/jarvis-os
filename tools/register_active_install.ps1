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
if not exist "%JARVIS_ROOT%\.git" goto :missing

cd /d "%JARVIS_ROOT%"
echo [0/3] JARVIS launcher guncelleniyor...
git fetch origin main >nul 2>&1
if errorlevel 1 goto :bootstrap_failed
git checkout origin/main -- tools\update_active_install.ps1 tools\setup_and_start.ps1 START_JARVIS.bat >nul 2>&1
if errorlevel 1 goto :bootstrap_failed

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_ROOT%\tools\update_active_install.ps1"
exit /b %ERRORLEVEL%

:bootstrap_failed
echo En guncel JARVIS baslaticisi alinamadi.
pause
exit /b 1

:missing
echo JARVIS aktif kurulum yolu bulunamadi.
echo JARVIS Tamir ve Ac dosyasini bir kez calistirin.
pause
exit /b 1
'@
Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding ascii

# The desktop shortcut runs through a Windows Script Host wrapper to hide
# the initial CMD/PowerShell console. Keep the original BAT available for
# troubleshooting, and capture the hidden launcher's output in a log.
$hiddenLauncherPath = Join-Path $projectsRoot 'JARVIS_AC_GIZLI.vbs'
$hiddenLauncher = @'
CreateObject("WScript.Shell").Run "cmd.exe /d /c C:\Projects\JARVIS_AC.bat > C:\Projects\JARVIS_AC.log 2>&1", 0, False
'@
Set-Content -LiteralPath $hiddenLauncherPath -Value $hiddenLauncher -Encoding ascii

$desktop = [Environment]::GetFolderPath('Desktop')
if ($desktop) {
    $shortcutPath = Join-Path $desktop 'JARVIS AC.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Join-Path $env:WINDIR 'System32\wscript.exe')
    $shortcut.Arguments = ('"' + $hiddenLauncherPath + '"')
    $shortcut.WorkingDirectory = $projectsRoot
    $shortcut.Description = 'JARVIS arka planda baslat; log: C:\Projects\JARVIS_AC.log'
    $shortcut.Save()
}

Write-Host "      Aktif JARVIS: $resolvedRoot" -ForegroundColor Green
Write-Host "      Bundan sonra masaustundeki JARVIS AC kisayolunu kullanin." -ForegroundColor Green
