param(
    [switch]$SetupOnly,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$VenvRoot = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$Requirements = Join-Path $ProjectRoot 'requirements.txt'
$RequirementsStamp = Join-Path $VenvRoot '.requirements.sha256'
$EnvironmentFile = Join-Path $ProjectRoot '.env'
$EnvironmentExample = Join-Path $ProjectRoot '.env.example'
$ControlCenter = Join-Path $ProjectRoot 'control_center.py'
$LogRoot = Join-Path $ProjectRoot 'workspace\control_center\logs'
$StdoutPath = Join-Path $LogRoot 'launcher.stdout.log'
$StderrPath = Join-Path $LogRoot 'launcher.stderr.log'
$TokenPath = Join-Path $ProjectRoot 'workspace\control_center\session.token'

function Resolve-JarvisPython {
    $launchers = @()
    $py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($py) {
        $launchers += ,@($py.Source, '-3.13')
        $launchers += ,@($py.Source, '-3')
    }
    $pythonCommands = Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\python.exe' }
    foreach ($command in $pythonCommands) {
        $launchers += ,@($command.Source)
    }

    foreach ($launcher in $launchers) {
        $executable = $launcher[0]
        $prefix = @($launcher | Select-Object -Skip 1)
        try {
            $resolved = & $executable @prefix -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2>$null
            $resolvedPath = @($resolved)[-1]
            if ($LASTEXITCODE -eq 0 -and $resolvedPath -and (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
                return [System.IO.Path]::GetFullPath($resolvedPath)
            }
        } catch { continue }
    }
    throw 'Python 3.11 veya yenisi bulunamadi. Python 3.13 x64 kurup START_JARVIS.bat dosyasini yeniden acin.'
}

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step basarisiz oldu (cikis kodu $LASTEXITCODE)." }
}

function Test-ControlCenterHealth([string]$Token) {
    if (-not $Token -or $Token.Length -lt 32) { return $false }
    try {
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $cookie = New-Object System.Net.Cookie('jarvis_session', $Token, '/', '127.0.0.1')
        $session.Cookies.Add($cookie)
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -WebSession $session `
            -Method Get -TimeoutSec 3 -ErrorAction Stop
        return ($response.backend_alive -eq $true)
    } catch { return $false }
}

Set-Location -LiteralPath $ProjectRoot
$SystemPython = Resolve-JarvisPython
Write-Host "[1/5] Python bulundu: $SystemPython" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host '[2/5] Guvenli proje ortami olusturuluyor...' -ForegroundColor Cyan
    & $SystemPython -m venv $VenvRoot
    Assert-LastExitCode 'Sanal ortam kurulumu'
} else {
    Write-Host '[2/5] Proje ortami hazir.' -ForegroundColor Green
}

$requirementsHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $RequirementsStamp) {
    (Get-Content -LiteralPath $RequirementsStamp -Raw).Trim()
} else { '' }
if ($requirementsHash -ne $installedHash) {
    Write-Host '[3/5] Gerekli hafif paketler kuruluyor/guncelleniyor...' -ForegroundColor Cyan
    & $VenvPython -m pip install --disable-pip-version-check -r $Requirements
    Assert-LastExitCode 'Paket kurulumu'
    Set-Content -LiteralPath $RequirementsStamp -Value $requirementsHash -Encoding ascii
} else {
    Write-Host '[3/5] Paketler guncel.' -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)) {
    Copy-Item -LiteralPath $EnvironmentExample -Destination $EnvironmentFile
    Write-Host '[4/5] .env olusturuldu. API anahtari eklenene kadar AI gorevleri eksik gorunebilir.' -ForegroundColor Yellow
} else {
    Write-Host '[4/5] Yerel .env korundu; uzerine yazilmadi.' -ForegroundColor Green
}

$ffmpeg = Join-Path $ProjectRoot 'tools\ffmpeg\bin\ffmpeg.exe'
if (-not (Test-Path -LiteralPath $ffmpeg -PathType Leaf)) {
    throw 'Yerel FFmpeg bulunamadi; video render hatti eksik.'
}
$claude = Get-Command claude.exe -CommandType Application -ErrorAction SilentlyContinue
if (-not $claude) { $claude = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue }
if ($claude) {
    Write-Host "      Claude Code bulundu: $($claude.Source)" -ForegroundColor Green
} else {
    Write-Host '      Claude Code kurulu degil; istege bagli, JARVIS onsuz da calisir.' -ForegroundColor DarkYellow
}

if ($SetupOnly) {
    Write-Host '[5/5] Kurulum tamamlandi. Baslatma -SetupOnly nedeniyle atlandi.' -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$token = if (Test-Path -LiteralPath $TokenPath -PathType Leaf) {
    (Get-Content -LiteralPath $TokenPath -Raw).Trim()
} else { '' }

if (-not (Test-ControlCenterHealth $token)) {
    Write-Host '[5/5] JARVIS Control Center baslatiliyor...' -ForegroundColor Cyan
    Start-Process -FilePath $VenvPython -ArgumentList @(
        "`"$ControlCenter`"", '--host', '127.0.0.1', '--port', $Port, '--no-bootstrap-output', '--fresh-session'
    ) -WorkingDirectory $ProjectRoot -RedirectStandardOutput $StdoutPath `
      -RedirectStandardError $StderrPath -WindowStyle Hidden | Out-Null

    $healthy = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath $TokenPath -PathType Leaf) {
            $token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
            if (Test-ControlCenterHealth $token) { $healthy = $true; break }
        }
    }
    if (-not $healthy) {
        throw "Control Center 45 saniyede hazir olmadi. Log: $StderrPath"
    }
} else {
    Write-Host '[5/5] Control Center zaten calisiyor.' -ForegroundColor Green
}

$url = "http://127.0.0.1:$Port/?token=$token"
Start-Process $url
Write-Host 'JARVIS HAZIR. Panel tarayicida acildi.' -ForegroundColor Green
Write-Host 'Guvenlik: yalnizca bu bilgisayarda 127.0.0.1 adresinde calisiyor.' -ForegroundColor DarkGray
