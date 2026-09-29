[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [switch]$NoBrowser
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$installDashboard = Join-Path $PSScriptRoot 'Install-WebDashboard.ps1'
if (-not (Test-Path -LiteralPath $installDashboard)) {
    throw "Missing dashboard installer: $installDashboard"
}

$pythonExe = ''
try {
    $pythonExe = (& python -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
}
catch {
}
if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python 3 was not found in PATH. Install Python 3 with Add Python to PATH, then run Setup.cmd again.'
}

& $installDashboard -Port $Port

$url = "http://127.0.0.1:$Port/"
Write-Host "Dashboard ready: $url"
if (-not $NoBrowser) {
    Start-Process $url
}
