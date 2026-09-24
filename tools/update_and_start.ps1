param(
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TargetBranch = 'codex/youtube-planning-gemini-images'
$ReadyBranch = 'jarvis-ready'
$SetupScript = Join-Path $PSScriptRoot 'setup_and_start.ps1'

function Invoke-Git([string[]]$Arguments, [string]$Step) {
    & git.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Step basarisiz oldu (git cikis kodu $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git'))) {
    throw "Bu klasor Git deposu degil: $ProjectRoot"
}
if (-not (Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'Git bulunamadi. Git for Windows kurulumunu kontrol edin.'
}

Set-Location -LiteralPath $ProjectRoot
$OriginalHead = [string](& git.exe rev-parse HEAD)
$OriginalHead = $OriginalHead.Trim()
if ($LASTEXITCODE -ne 0 -or -not $OriginalHead) {
    throw 'Mevcut JARVIS surumu okunamadi.'
}
$OriginalBranch = [string](& git.exe branch --show-current)
$OriginalBranch = $OriginalBranch.Trim()
$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupBranch = "backup/jarvis-before-update-$Timestamp"
$StashCreated = $false

Write-Host '[1/4] Mevcut JARVIS guvenli dala kaydediliyor...' -ForegroundColor Cyan
Invoke-Git -Arguments @('branch', $BackupBranch, $OriginalHead) -Step 'Guvenlik dali olusturma'
Write-Host "      Guvenlik dali: $BackupBranch" -ForegroundColor DarkGray

$LocalChanges = @(& git.exe status --porcelain --untracked-files=all)
if ($LocalChanges.Count -gt 0) {
    Write-Host '      Yerel degisiklikler gecici kasada korunuyor...' -ForegroundColor Yellow
    Invoke-Git -Arguments @('stash', 'push', '--include-untracked', '-m', "jarvis-safe-update-$Timestamp") `
        -Step 'Yerel degisiklikleri koruma'
    $StashCreated = $true
}

try {
    Write-Host '[2/4] GitHub guncel surumu aliniyor...' -ForegroundColor Cyan
    Invoke-Git -Arguments @('fetch', 'origin', $TargetBranch) -Step 'GitHub guncelleme'

    Write-Host '[3/4] Dogrulanmis JARVIS dali aciliyor...' -ForegroundColor Cyan
    Invoke-Git -Arguments @('switch', '-C', $ReadyBranch, "origin/$TargetBranch") -Step 'Guncel dala gecis'

    Write-Host '[4/4] JARVIS baslatiliyor...' -ForegroundColor Cyan
    Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SetupScript -Port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "JARVIS baslatma basarisiz oldu (cikis kodu $LASTEXITCODE)."
    }
} catch {
    Write-Host 'Guncelleme tamamlanamadi; onceki surum geri aciliyor...' -ForegroundColor Yellow
    if ($OriginalBranch) {
        & git.exe switch $OriginalBranch | Out-Null
    } else {
        & git.exe switch --detach $OriginalHead | Out-Null
    }
    if ($StashCreated) {
        & git.exe stash pop | Out-Null
    }
    throw
}

Write-Host 'JARVIS GUNCEL VE HAZIR.' -ForegroundColor Green
Write-Host "Geri donus noktasi: $BackupBranch" -ForegroundColor DarkGray
if ($StashCreated) {
    Write-Host 'Eski yerel degisiklikleriniz git stash icinde korundu; otomatik olarak yeni kodun ustune bindirilmedi.' -ForegroundColor Yellow
}
