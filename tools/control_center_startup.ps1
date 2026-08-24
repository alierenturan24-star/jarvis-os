param(
    [switch]$Install,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = 'JARVIS Control Center (Current User)'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Watchdog = Join-Path $ProjectRoot 'tools\start_control_center_watchdog.ps1'
$PowerShell = Join-Path $PSHOME 'powershell.exe'

function Resolve-ReliablePython {
    $candidates = Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\python.exe' }
    foreach ($candidate in $candidates) {
        $resolved = & $candidate.Source -c 'import sys; print(sys.executable)' 2>$null
        $resolvedPath = @($resolved)[-1]
        if ($LASTEXITCODE -eq 0 -and $resolvedPath -and (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
            return [System.IO.Path]::GetFullPath($resolvedPath)
        }
    }
    throw 'A working python.exe could not be resolved. Install Python or run this installer from its environment.'
}

$PythonExecutable = Resolve-ReliablePython
$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Watchdog`" -PythonExecutable `"$PythonExecutable`""

if (-not $Install -and -not $Remove) {
    Write-Output 'PLAN ONLY - no system change made.'
    Write-Output "Task: $TaskName"
    Write-Output 'Scope: current user, at logon, no administrator privilege requested.'
    Write-Output "Action: $PowerShell $Arguments"
    Write-Output "Working directory: $ProjectRoot"
    Write-Output "Python: $PythonExecutable"
    Write-Output 'Network: loopback 127.0.0.1:8765 only; no firewall or public-port change.'
    Write-Output 'Run again with -Install only after reviewing this plan.'
    exit 0
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    Write-Output "Removed: $TaskName"
    exit 0
}

$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description 'Starts the loopback-only JARVIS Control Center watchdog for the current user.' -Force | Out-Null
Write-Output "Installed or updated for current user: $TaskName"
