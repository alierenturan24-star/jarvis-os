param([int]$Port = 8765)

$ErrorActionPreference = 'SilentlyContinue'
$Setup = Join-Path $PSScriptRoot 'setup_and_start.ps1'

# Let the API response reach the browser and the old process release its port.
Start-Sleep -Seconds 3
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Setup -Port $Port
