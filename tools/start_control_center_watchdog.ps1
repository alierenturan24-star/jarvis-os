param(
    [int]$Port = 8765,
    [string]$PythonExecutable = '',
    [int]$RestartDelaySeconds = 5,
    [int]$MaxRestartDelaySeconds = 300,
    [int]$MaxRapidRestarts = 5,
    [int]$RapidExitWindowSeconds = 60
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ControlCenter = Join-Path $ProjectRoot 'control_center.py'
$LogRoot = Join-Path $ProjectRoot 'workspace\control_center\logs'
$LogPath = Join-Path $LogRoot 'watchdog.log'
$StdoutPath = Join-Path $LogRoot 'control_center.stdout.log'
$StderrPath = Join-Path $LogRoot 'control_center.stderr.log'
$TokenPath = Join-Path $ProjectRoot 'workspace\control_center\session.token'

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Write-WatchdogLog([string]$Message) {
    "[$((Get-Date).ToString('o'))] $Message" | Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Resolve-PythonExecutable([string]$Requested) {
    if ($Requested) {
        $resolved = [System.IO.Path]::GetFullPath($Requested)
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "Configured Python executable does not exist: $resolved"
        }
        return $resolved
    }
    $command = Get-Command python.exe -CommandType Application -ErrorAction Stop |
        Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\python.exe' } |
        Select-Object -First 1
    if (-not $command) { throw 'A real python.exe could not be resolved.' }
    return $command.Source
}

function Test-ControlCenterHealth {
    if (-not (Test-Path -LiteralPath $TokenPath -PathType Leaf)) { return $false }
    try {
        $token = (Get-Content -LiteralPath $TokenPath -Raw -ErrorAction Stop).Trim()
        if ($token.Length -lt 32) { return $false }
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $cookie = New-Object System.Net.Cookie('jarvis_session', $token, '/', '127.0.0.1')
        $session.Cookies.Add($cookie)
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -WebSession $session `
            -Method Get -TimeoutSec 3 -ErrorAction Stop
        return ($response.backend_alive -eq $true)
    } catch { return $false }
}

function Test-PortListening {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $wait = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $connected = $wait.AsyncWaitHandle.WaitOne(1000) -and $client.Connected
        $client.Close()
        return $connected
    } catch { return $false }
}

if (-not (Test-Path -LiteralPath $ControlCenter -PathType Leaf)) {
    throw "Control Center entry point does not exist: $ControlCenter"
}
$PythonExecutable = Resolve-PythonExecutable $PythonExecutable
Write-WatchdogLog "Watchdog started; root=$ProjectRoot; python=$PythonExecutable; endpoint=127.0.0.1:$Port"

$rapidRestarts = 0
while ($true) {
    if (Test-ControlCenterHealth) {
        Write-WatchdogLog 'A healthy Control Center already exists; monitoring it without starting a duplicate.'
        do { Start-Sleep -Seconds 10 } while (Test-ControlCenterHealth)
        Write-WatchdogLog 'The previously healthy Control Center stopped responding.'
    } elseif (Test-PortListening) {
        Write-WatchdogLog "ERROR: Port 127.0.0.1:$Port is occupied but the Control Center health check failed; launch suppressed."
        Start-Sleep -Seconds ([Math]::Min($MaxRestartDelaySeconds, 30))
        continue
    }

    $started = Get-Date
    Write-WatchdogLog 'Starting Control Center on loopback.'
    try {
        $process = Start-Process -FilePath $PythonExecutable -ArgumentList @(
            $ControlCenter, '--host', '127.0.0.1', '--port', $Port, '--no-bootstrap-output'
        ) -WorkingDirectory $ProjectRoot -RedirectStandardOutput $StdoutPath `
          -RedirectStandardError $StderrPath -NoNewWindow -PassThru -Wait
        $exitCode = $process.ExitCode
    } catch {
        $exitCode = -1
        Write-WatchdogLog "ERROR: Failed to create Control Center process: $($_.Exception.Message)"
    }

    $runtime = ((Get-Date) - $started).TotalSeconds
    if ($runtime -ge $RapidExitWindowSeconds) { $rapidRestarts = 0 } else { $rapidRestarts++ }
    $exponent = [Math]::Min($rapidRestarts, $MaxRapidRestarts)
    $delay = [Math]::Min($MaxRestartDelaySeconds, $RestartDelaySeconds * [Math]::Pow(2, $exponent))
    if ($rapidRestarts -ge $MaxRapidRestarts) { $delay = $MaxRestartDelaySeconds }
    Write-WatchdogLog "Control Center exited (code=$exitCode, runtime=$([Math]::Round($runtime, 1))s); retry in $delay seconds."
    Start-Sleep -Seconds $delay
}
