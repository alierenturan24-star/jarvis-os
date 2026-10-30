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
$InstanceLockPath = Join-Path $ProjectRoot ("workspace\control_center\127.0.0.1_{0}.pid" -f $Port)

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

function Test-ControlCenterHealth([string]$Token, [string]$ExpectedBuild) {
    if (-not $Token -or $Token.Length -lt 32) { return $false }
    try {
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $cookie = New-Object System.Net.Cookie('jarvis_session', $Token, '/', '127.0.0.1')
        $session.Cookies.Add($cookie)
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/liveness" -WebSession $session `
            -Method Get -TimeoutSec 3 -ErrorAction Stop
        $runningBuild = [string]$response.process.build_identity
        $startupReady = if ($null -eq $response.startup_ready) { $true } else { [bool]$response.startup_ready }
        return ($response.backend_alive -eq $true -and $runningBuild -eq $ExpectedBuild -and $startupReady)
    } catch { return $false }
}

function Get-ControlCenterLiveness([string]$Token) {
    if (-not $Token -or $Token.Length -lt 32) { return $null }
    try {
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $cookie = New-Object System.Net.Cookie('jarvis_session', $Token, '/', '127.0.0.1')
        $session.Cookies.Add($cookie)
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/liveness" -WebSession $session -Method Get -TimeoutSec 3 -ErrorAction Stop
    } catch { return $null }
}

function Open-JarvisPanel([string]$Url) {
    $browserCandidates = @(
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }

    foreach ($browser in $browserCandidates) {
        try {
            Start-Process -FilePath $browser -ArgumentList @('--new-window', $Url) -ErrorAction Stop | Out-Null
            return
        } catch { continue }
    }

    try {
        Start-Process $Url -ErrorAction Stop | Out-Null
    } catch {
        Start-Process -FilePath 'explorer.exe' -ArgumentList $Url -ErrorAction Stop | Out-Null
    }
}


function Clear-StaleJarvisListener {
    $candidateIds = New-Object System.Collections.Generic.HashSet[int]

    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        [void]$candidateIds.Add([int]$listener.OwningProcess)
    }

    if (Test-Path -LiteralPath $InstanceLockPath -PathType Leaf) {
        try {
            $lockOwner = Get-Content -LiteralPath $InstanceLockPath -Raw | ConvertFrom-Json
            if ($lockOwner.pid) { [void]$candidateIds.Add([int]$lockOwner.pid) }
        } catch {}
    }

    foreach ($ownerId in @($candidateIds)) {
        if ($ownerId -le 0 -or $ownerId -eq $PID) { continue }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
        $commandLine = if ($process) { [string]$process.CommandLine } else { '' }
        if ($commandLine -match '(?i)control_center\.py' -and
            $commandLine -match ('(?i)--port\s+["'']?{0}\b' -f $Port)) {
            Write-Host "      Eski/takilmis JARVIS islemi kapatiliyor (PID $ownerId)..." -ForegroundColor Yellow
            Stop-Process -Id $ownerId -Force -ErrorAction SilentlyContinue
        }
    }

    Start-Sleep -Milliseconds 700

    if (Test-Path -LiteralPath $InstanceLockPath -PathType Leaf) {
        try {
            $lockOwner = Get-Content -LiteralPath $InstanceLockPath -Raw | ConvertFrom-Json
            $lockPid = [int]$lockOwner.pid
            if ($lockPid -le 0 -or -not (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)) {
                Remove-Item -LiteralPath $InstanceLockPath -Force -ErrorAction SilentlyContinue
            }
        } catch {
            Remove-Item -LiteralPath $InstanceLockPath -Force -ErrorAction SilentlyContinue
        }
    }

    $remaining = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($remaining.Count -gt 0) {
        $owners = ($remaining | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
        throw "Port $Port baska bir uygulama tarafindan kullaniliyor (PID: $owners)."
    }
}

Set-Location -LiteralPath $ProjectRoot
$ExpectedBuild = (& git.exe -C $ProjectRoot rev-parse --short=12 HEAD).Trim()
if (-not $ExpectedBuild) { throw 'JARVIS surum kimligi okunamadi.' }
# Child Control Center inherits this exact source identity. Mission reports use
# the same value so persisted/old results can be distinguished from a fresh run.
$env:JARVIS_BUILD_ID = $ExpectedBuild
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

if (-not (Test-ControlCenterHealth $token $ExpectedBuild)) {
    Write-Host '[5/5] JARVIS Control Center baslatiliyor...' -ForegroundColor Cyan
    Clear-StaleJarvisListener
    $controlProcess = Start-Process -FilePath $VenvPython -ArgumentList @(
        "`"$ControlCenter`"", '--host', '127.0.0.1', '--port', $Port, '--no-bootstrap-output', '--fresh-session'
    ) -WorkingDirectory $ProjectRoot -RedirectStandardOutput $StdoutPath `
      -RedirectStandardError $StderrPath -WindowStyle Hidden -PassThru

    $healthy = $false
    $backendBound = $false
    $startupError = ''
    $startupStage = ''
    $startupSeconds = 90
    for ($attempt = 0; $attempt -lt $startupSeconds; $attempt++) {
        Start-Sleep -Seconds 1
        try { $controlProcess.Refresh() } catch {}
        if ($controlProcess.HasExited) { break }
        if (Test-Path -LiteralPath $TokenPath -PathType Leaf) {
            $token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
            $live = Get-ControlCenterLiveness $token
            if ($live) {
                $runningBuild = [string]$live.process.build_identity
                if ($live.backend_alive -eq $true -and $runningBuild -eq $ExpectedBuild) {
                    $backendBound = $true
                    $startupStage = [string]$live.startup_stage
                    $startupError = [string]$live.startup_error
                    if ($startupError) { break }
                    if ($live.startup_ready -eq $true -or $live.runtime_state -ne 'BOOTING') {
                        $healthy = $true
                        break
                    }
                    if (($attempt + 1) % 15 -eq 0) {
                        $stageText = if ($startupStage) { $startupStage } else { 'BOOTING' }
                        Write-Host ("      Control Center ayakta; servis hazirlaniyor: {0}" -f $stageText) -ForegroundColor DarkYellow
                    }
                }
            }
        }
    }

    if (-not $healthy -and $backendBound -and -not $startupError -and -not $controlProcess.HasExited) {
        $stageText = if ($startupStage) { $startupStage } else { 'BOOTING' }
        Write-Host ("      Control Center ayakta; agir servis hazirligi arka planda devam ediyor ({0})." -f $stageText) -ForegroundColor Yellow
        $healthy = $true
    }

    if (-not $healthy) {
        if (-not $controlProcess.HasExited) {
            Write-Host "      Basarisiz baslatma sureci temizleniyor (PID $($controlProcess.Id))..." -ForegroundColor Yellow
            Stop-Process -Id $controlProcess.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
        }
        if (Test-Path -LiteralPath $InstanceLockPath -PathType Leaf) {
            try {
                $lockOwner = Get-Content -LiteralPath $InstanceLockPath -Raw | ConvertFrom-Json
                if ([int]$lockOwner.pid -eq [int]$controlProcess.Id) {
                    Remove-Item -LiteralPath $InstanceLockPath -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }

        Write-Host ''
        Write-Host '----- JARVIS STARTUP ERROR LOG -----' -ForegroundColor Red
        if ($startupError) {
            Write-Host ("Startup error: {0}" -f $startupError) -ForegroundColor DarkRed
        }
        if (Test-Path -LiteralPath $StderrPath -PathType Leaf) {
            Get-Content -LiteralPath $StderrPath -Tail 80 | ForEach-Object { Write-Host $_ -ForegroundColor DarkRed }
        } else {
            Write-Host 'launcher.stderr.log olusturulamadi.' -ForegroundColor DarkRed
        }
        if (Test-Path -LiteralPath $StdoutPath -PathType Leaf) {
            Write-Host '----- STDOUT SON SATIRLAR -----' -ForegroundColor DarkYellow
            Get-Content -LiteralPath $StdoutPath -Tail 40 | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
        }
        Write-Host '------------------------------------' -ForegroundColor Red
        $exitDetail = if ($controlProcess.HasExited) { " Islem cikis kodu: $($controlProcess.ExitCode)." } else { '' }
        throw "Control Center $startupSeconds saniyede hazir olmadi.$exitDetail Log: $StderrPath"
    }
} else {
    Write-Host '[5/5] Control Center zaten calisiyor.' -ForegroundColor Green
}

$url = "http://127.0.0.1:$Port/?token=$token"
$registerActive = Join-Path $ProjectRoot 'tools\register_active_install.ps1'
if (Test-Path -LiteralPath $registerActive -PathType Leaf) {
    & $registerActive -ProjectRoot $ProjectRoot
}
# Open the dashboard AND start at most one queued, non-publishing mission.
try {
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $session.Cookies.Add((New-Object System.Net.Cookie('jarvis_session', $token, '/', '127.0.0.1')))
    $launch = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/control/run-pending" -WebSession $session -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 8 -ErrorAction Stop
    if ($launch.started -eq $true) {
        Write-Host "BEKLEYEN VIDEO GOREVI BASLADI: $($launch.mission_id)" -ForegroundColor Green
    } else {
        Write-Host "Otomatik gorev baslatilmadi: $($launch.reason)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Otomatik gorev baslatilamadi: $($_.Exception.Message)" -ForegroundColor Yellow
}
Open-JarvisPanel $url
Write-Host 'JARVIS HAZIR. Panel tarayicida acildi.' -ForegroundColor Green
Write-Host 'Guvenlik: yalnizca bu bilgisayarda 127.0.0.1 adresinde calisiyor.' -ForegroundColor DarkGray
