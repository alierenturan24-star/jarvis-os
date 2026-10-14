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
$parent = Split-Path -Parent $IntegrationRoot
$SetupStatePath = Join-Path $parent 'MoneyPrinterTurbo.setup.json'

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

function Write-SetupState([string]$Status, [string]$Message = '', [string]$PythonPath = '') {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    @{
        status = $Status
        message = $Message
        python = $PythonPath
        revision = $PinnedRevision
        updated_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $SetupStatePath -Encoding utf8
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

Write-SetupState 'RUNNING' 'Kurulum baslatildi.'
try {

if (-not (Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    throw 'Git for Windows bulunamadi.'
}

New-Item -ItemType Directory -Force -Path $parent | Out-Null
if ((Test-Path -LiteralPath $IntegrationRoot) -and -not (Test-Path -LiteralPath (Join-Path $IntegrationRoot '.git'))) {
    # A ZIP/manual copy at the managed path makes `git clone` fail with an
    # opaque "directory not empty" message. Preserve it instead of deleting
    # anything, then create the pinned managed checkout cleanly.
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
    $backup = "$IntegrationRoot.unmanaged-$stamp"
    Move-Item -LiteralPath $IntegrationRoot -Destination $backup
    Write-Host "Yonetilmeyen eski kaynak korundu: $backup" -ForegroundColor Yellow
}
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
    # Prefer the most broadly supported CPython releases. The pinned upstream
    # accepts >=3.11; each candidate is verified instead of trusting PATH.
    foreach ($selector in @('-3.11', '-3.12', '-3.13', '-3')) {
        $candidate = (& $py.Source $selector -c "import sys; print(sys.executable if sys.version_info >= (3,11) else '')" 2>$null | Select-Object -Last 1)
        if ($candidate) { $systemPython = $candidate; break }
    }
}
if (-not $systemPython) {
    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($python) {
        $candidate = (& $python.Source -c "import sys; print(sys.executable if sys.version_info >= (3,11) else '')" 2>$null | Select-Object -Last 1)
        if ($candidate) { $systemPython = $candidate }
    }
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
$env:UV_PROJECT_ENVIRONMENT = Join-Path $IntegrationRoot '.venv'
$env:UV_LINK_MODE = 'copy'
& $uvPath sync --frozen --no-dev --python $systemPython --project $IntegrationRoot
Assert-ExitCode 'MoneyPrinterTurbo bagimlilik kurulumu'
$venvPython = Join-Path $IntegrationRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'MoneyPrinterTurbo .venv olusturulamadi.'
}
& $venvPython -c "import moviepy, edge_tts; print('MPT_RUNTIME_OK')"
Assert-ExitCode 'MoneyPrinterTurbo calisma ortami dogrulama'

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

Write-SetupState 'READY' 'Kurulum ve calisma ortami dogrulandi.' $venvPython
Write-Host 'MoneyPrinterTurbo JARVIS icin hazir. Otomatik yayin kapali.' -ForegroundColor Green
} catch {
    Write-SetupState 'FAILED' $_.Exception.Message $systemPython
    throw
}

