param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$TargetBranch = 'codex/youtube-planning-gemini-images'
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
if (-not (Test-Path -LiteralPath (Join-Path $NextRoot '.git'))) {
    Invoke-Git @('worktree', 'add', '--detach', $NextRoot, $RemoteHead) 'Yeni aktif JARVIS klasoru olusturulamadi.'
}

$CurrentEnv = Join-Path $CurrentRoot '.env'
if (Test-Path -LiteralPath $CurrentEnv -PathType Leaf) {
    Copy-Item -LiteralPath $CurrentEnv -Destination (Join-Path $NextRoot '.env') -Force
}
$CurrentWorkspace = Join-Path $CurrentRoot 'workspace'
$NextWorkspace = Join-Path $NextRoot 'workspace'
if (Test-Path -LiteralPath $CurrentWorkspace -PathType Container) {
    & robocopy.exe $CurrentWorkspace $NextWorkspace /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'JARVIS calisma kayitlari yeni surume kopyalanamadi.' }
}

Write-Host '[3/3] Guncel panel baslatiliyor...' -ForegroundColor Cyan
& (Join-Path $NextRoot 'START_JARVIS.bat')
exit $LASTEXITCODE
