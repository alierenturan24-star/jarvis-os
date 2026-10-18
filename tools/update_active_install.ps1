param([int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$CurrentRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $CurrentRoot

function Resolve-CanonicalJarvisRoot {
    $common = [string](& git.exe -C $CurrentRoot rev-parse --git-common-dir)
    if ($LASTEXITCODE -ne 0 -or -not $common.Trim()) {
        throw 'JARVIS Git ana klasoru bulunamadi.'
    }
    $common = $common.Trim()
    if (-not [System.IO.Path]::IsPathRooted($common)) {
        $common = [System.IO.Path]::GetFullPath((Join-Path $CurrentRoot $common))
    }
    $common = [System.IO.Path]::GetFullPath($common)

    if ((Split-Path -Leaf $common) -eq '.git') {
        return [System.IO.Path]::GetFullPath((Split-Path -Parent $common))
    }
    return $CurrentRoot
}

$CanonicalRoot = Resolve-CanonicalJarvisRoot
Write-Host '[1/3] JARVIS ana kurulumu bulunuyor...' -ForegroundColor Cyan
Write-Host "      Ana kurulum: $CanonicalRoot" -ForegroundColor DarkGray

Write-Host '[2/3] En guncel guvenli updater aliniyor...' -ForegroundColor Cyan
& git.exe -C $CanonicalRoot fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub guncellemesi alinamadi.' }

$bootstrapFiles = @(
    'UPDATE_JARVIS.bat',
    'START_JARVIS.bat',
    'tools/update_and_start.ps1',
    'tools/setup_and_start.ps1',
    'tools/register_active_install.ps1',
    'tools/update_active_install.ps1'
)
& git.exe -C $CanonicalRoot checkout origin/main -- @bootstrapFiles
if ($LASTEXITCODE -ne 0) { throw 'Guncel JARVIS baslaticilari alinamadi.' }

Write-Host '[3/3] Guvenli yerinde guncelleme baslatiliyor...' -ForegroundColor Cyan
$Updater = Join-Path $CanonicalRoot 'tools\update_and_start.ps1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Updater -Port $Port
exit $LASTEXITCODE
