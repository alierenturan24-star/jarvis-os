param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$TargetBranch = 'main'
$CurrentRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $CurrentRoot

function Invoke-Git([string[]]$Arguments, [string]$Failure) {
    & git.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

Write-Host '[1/3] JARVIS guncel surumu kontrol ediliyor...' -ForegroundColor Cyan
Invoke-Git @('fetch', '--progress', 'origin', "+refs/heads/${TargetBranch}:refs/remotes/origin/${TargetBranch}") `
    'GitHub guncellemesi alinamadi.'
$RemoteHead = (& git.exe rev-parse "refs/remotes/origin/$TargetBranch").Trim()
$CurrentHead = (& git.exe rev-parse HEAD).Trim()
if (-not $RemoteHead) { throw 'GitHub surumu okunamadi.' }

if ($RemoteHead -eq $CurrentHead) {
    Write-Host '[2/3] JARVIS zaten guncel.' -ForegroundColor Green
    Write-Host '[3/3] Panel aciliyor...' -ForegroundColor Cyan
    & (Join-Path $CurrentRoot 'tools\setup_and_start.ps1') -Port $Port
    exit $LASTEXITCODE
}

$ShortHead = $RemoteHead.Substring(0, 12)
$NextRoot = "C:\Projects\jarvis-active-$ShortHead"
Write-Host "[2/3] Yeni surum guvenli aktif klasore kuruluyor: $ShortHead" -ForegroundColor Cyan

Write-Host '      [2a] Git worktree hazirlaniyor...' -ForegroundColor DarkGray
& git.exe worktree prune
if ($LASTEXITCODE -ne 0) { throw 'Eski worktree kayitlari temizlenemedi.' }

$NextGit = Join-Path $NextRoot '.git'
if (-not (Test-Path -LiteralPath $NextGit)) {
    if (Test-Path -LiteralPath $NextRoot) {
        # This directory name is generated solely from the remote commit.
        # If it has no .git marker it is an incomplete previous install and
        # can be safely recreated without touching the user's main checkout.
        Write-Host '      [2b] Yarim kalmis aktif klasor temizleniyor...' -ForegroundColor Yellow
        Remove-Item -LiteralPath $NextRoot -Recurse -Force
    }
    Write-Host '      [2c] Yeni kod dosyalari hazirlaniyor...' -ForegroundColor DarkGray
    Invoke-Git @('worktree', 'add', '--detach', $NextRoot, $RemoteHead) 'Yeni aktif JARVIS klasoru olusturulamadi.'
} else {
    Write-Host '      [2c] Aktif kod klasoru zaten hazir.' -ForegroundColor DarkGray
}

Write-Host '      [2d] Yerel ayarlar ve kucuk durum dosyasi tasiniyor...' -ForegroundColor DarkGray
$CurrentEnv = Join-Path $CurrentRoot '.env'
if (Test-Path -LiteralPath $CurrentEnv -PathType Leaf) {
    Copy-Item -LiteralPath $CurrentEnv -Destination (Join-Path $NextRoot '.env') -Force
}

# Do NOT recursively copy workspace. It can contain large MP4/audio/images and
# previously made the launcher appear frozen for minutes with no output.
# Preserve only the compact Control Center state needed for missions/settings.
$CurrentState = Join-Path $CurrentRoot 'workspace\control_center\state.json'
$NextStateDir = Join-Path $NextRoot 'workspace\control_center'
$NextState = Join-Path $NextStateDir 'state.json'
if (Test-Path -LiteralPath $CurrentState -PathType Leaf) {
    New-Item -ItemType Directory -Force -Path $NextStateDir | Out-Null
    Copy-Item -LiteralPath $CurrentState -Destination $NextState -Force
}

Write-Host '[3/3] Guncel panel baslatiliyor...' -ForegroundColor Cyan
& (Join-Path $NextRoot 'START_JARVIS.bat')
exit $LASTEXITCODE
