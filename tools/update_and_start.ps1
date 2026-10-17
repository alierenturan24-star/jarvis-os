param(
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$TargetBranch = 'main'
$SetupScript = Join-Path $PSScriptRoot 'setup_and_start.ps1'
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$CriticalTests = @(
    'src/mission/tests/test_swiss_insider_conditional_routing.py::test_exact_current_user_command_forces_research_before_media',
    'src/mission/tests/test_research_department_timeout.py::test_media_research_budget_covers_all_bounded_research_passes',
    'src/research/tests/test_manager_timeout.py::test_each_search_call_is_clamped_to_provider_timeout',
    'src/research/tests/test_story_corroboration_regression.py',
    'src/control_center/tests/test_instance_lock_recovery.py',
    'src/control_center/tests/test_control_center.py::test_liveness_is_fast_process_state_only',
    'src/control_center/tests/test_control_center.py::test_health_does_not_probe_provider_networks',
    'src/mission/tests/test_recovery.py::test_recovered_research_requeues_cancelled_media_dependency',
    'src/mission/tests/test_recovery.py::test_research_timeout_retry_keeps_full_original_budget',
    'src/providers/tests/test_yt_dlp_media_provider.py',
    'src/providers/tests/test_wikimedia_media_provider.py',
    'src/media/tests/test_production_helpers.py'
)

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
$RunId = "$Timestamp-$PID"
$ReadyBranch = "jarvis-ready-$RunId"
# PID eklenerek yarim kalmis onceki bir guncellemenin ayni saniye adiyla
# cakismasi engellenir. Yine de isim mevcutsa sayacla benzersizlestirilir.
$BackupBranch = "backup/jarvis-before-update-$RunId"
$BackupSuffix = 1
& git.exe show-ref --verify --quiet "refs/heads/$BackupBranch"
while ($LASTEXITCODE -eq 0) {
    $BackupBranch = "backup/jarvis-before-update-$RunId-$BackupSuffix"
    $BackupSuffix++
    & git.exe show-ref --verify --quiet "refs/heads/$BackupBranch"
}
$StashCreated = $false

Write-Host '[1/6] Mevcut JARVIS guvenli dala kaydediliyor...' -ForegroundColor Cyan
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
    Write-Host '[2/6] GitHub guncel surumu aliniyor...' -ForegroundColor Cyan
    Invoke-Git -Arguments @('fetch', 'origin', $TargetBranch) -Step 'GitHub guncelleme'

    Write-Host '[3/6] Dogrulanmis JARVIS dali aciliyor...' -ForegroundColor Cyan
    # Sabit bir dal adi baska bir Git worktree tarafindan kullaniliyor olabilir.
    # Her calistirmada benzersiz dal kullanmak eski guvenli kurulumlara dokunmadan
    # Windows'taki "already used by worktree" hatasini onler.
    Invoke-Git -Arguments @('switch', '-C', $ReadyBranch, "origin/$TargetBranch") -Step 'Guncel dala gecis'

    Write-Host '[4/6] Bagimliliklar ve yerel araclar dogrulaniyor...' -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SetupScript -SetupOnly -Port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "JARVIS hazirlik asamasi basarisiz oldu (cikis kodu $LASTEXITCODE)."
    }
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "JARVIS Python ortami bulunamadi: $VenvPython"
    }

    Write-Host '[5/6] Kritik Research -> Media testleri calistiriliyor...' -ForegroundColor Cyan
    & $VenvPython -m pytest -q @CriticalTests
    if ($LASTEXITCODE -ne 0) {
        throw "Kritik JARVIS testleri basarisiz oldu (cikis kodu $LASTEXITCODE)."
    }
    Write-Host '      Kritik testler BASARILI.' -ForegroundColor Green

    Write-Host '[6/6] JARVIS baslatiliyor...' -ForegroundColor Cyan
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
