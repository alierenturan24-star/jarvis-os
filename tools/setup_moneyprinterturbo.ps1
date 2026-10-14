param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$PinnedRevision = 'c184fccd05621d7a654b6e6ea34102a0a0de0657'
$Repository = 'https://github.com/harry0703/MoneyPrinterTurbo.git'
$DefaultRoot = 'C:\Projects\jarvis-integrations\MoneyPrinterTurbo'
$IntegrationRoot = if ($env:MONEYPRINTERTURBO_ROOT) {
    [System.IO.Path]::GetFullPath($env:MONEYPRINTERTURBO_ROOT)
} else { $DefaultRoot }

function Assert-ExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step basarisiz oldu (cikis kodu $LASTEXITCODE)." }
}

function Set-SafeMoneyPrinterConfig([string]$ConfigPath) {
    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $content = ([regex]'(?m)^llm_provider\s*=\s*"[^"]*"').Replace($content, 'llm_provider = "claude_code"', 1)
    $content = ([regex]'(?m)^upload_post_enabled\s*=\s*(true|false)').Replace($content, 'upload_post_enabled = false', 1)
    $content = ([regex]'(?m)^upload_post_auto_upload\s*=\s*(true|false)').Replace($content, 'upload_post_auto_upload = false', 1)
    Set-Content -LiteralPath $ConfigPath -Value $content -Encoding utf8
}

if ($DryRun) {
    [pscustomobject]@{
        root = $IntegrationRoot
        repository = $Repository
        revision = $PinnedRevision
        isolated = $true
        claude_code = $true
        publishing = $false
    } | ConvertTo-Json
    exit 0
}

if (-not (Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'Git for Windows bulunamadi.'
}

$parent = Split-Path -Parent $IntegrationRoot
New-Item -ItemType Directory -Force -Path $parent | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $IntegrationRoot '.git'))) {
    Write-Host 'MoneyPrinterTurbo ayri ve guvenli klasore aliniyor...' -ForegroundColor Cyan
    & git.exe clone --filter=blob:none --no-checkout $Repository $IntegrationRoot
    Assert-ExitCode 'MoneyPrinterTurbo indirme'
}

& git.exe -C $IntegrationRoot fetch --depth 1 origin $PinnedRevision
Assert-ExitCode 'MoneyPrinterTurbo sabit surum alma'
& git.exe -C $IntegrationRoot checkout --detach $PinnedRevision
Assert-ExitCode 'MoneyPrinterTurbo sabit surume gecis'

$systemPython = $null
$py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
if ($py) {
    $systemPython = (& $py.Source -3.13 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    if (-not $systemPython) {
        $systemPython = (& $py.Source -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    }
}
if (-not $systemPython) {
    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($python) { $systemPython = $python.Source }
}
if (-not $systemPython) { throw 'Python 3.11 veya yenisi bulunamadi.' }

$uv = Get-Command uv.exe -CommandType Application -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host 'MoneyPrinterTurbo paket yoneticisi ayri ortama kuruluyor...' -ForegroundColor Cyan
    & $systemPython -m pip install --disable-pip-version-check 'uv>=0.9.4,<1'
    Assert-ExitCode 'uv kurulumu'
    $scripts = Join-Path (Split-Path -Parent $systemPython) 'Scripts\uv.exe'
    if (Test-Path -LiteralPath $scripts) { $uvPath = $scripts }
    else {
        $uv = Get-Command uv.exe -CommandType Application -ErrorAction SilentlyContinue
        if (-not $uv) { throw 'uv kuruldu ancak calistirilabilir dosya bulunamadi.' }
        $uvPath = $uv.Source
    }
} else { $uvPath = $uv.Source }

Write-Host 'MoneyPrinterTurbo izole Python ortami hazirlaniyor...' -ForegroundColor Cyan
& $uvPath sync --frozen --no-dev --project $IntegrationRoot
Assert-ExitCode 'MoneyPrinterTurbo bagimlilik kurulumu'

$config = Join-Path $IntegrationRoot 'config.toml'
if (-not (Test-Path -LiteralPath $config)) {
    Copy-Item -LiteralPath (Join-Path $IntegrationRoot 'config.example.toml') -Destination $config
}
Set-SafeMoneyPrinterConfig $config

$claude = Get-Command claude.exe -CommandType Application -ErrorAction SilentlyContinue
if (-not $claude) { $claude = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue }
$marker = @{
    installed_at = (Get-Date).ToUniversalTime().ToString('o')
    revision = $PinnedRevision
    llm_provider = 'claude_code'
    claude_cli_found = [bool]$claude
    publishing_enabled = $false
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $IntegrationRoot '.jarvis-integration.json') -Value $marker -Encoding utf8

Write-Host 'MoneyPrinterTurbo JARVIS icin hazir. Otomatik yayin kapali.' -ForegroundColor Green

