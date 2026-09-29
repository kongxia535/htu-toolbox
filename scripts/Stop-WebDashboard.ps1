[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repositoryRoot 'runtime'
$pidPath = Join-Path $runtimeDirectory 'dashboard.pid'
$serverScript = Join-Path $repositoryRoot 'web\server.py'
$stopped = $false

if (Test-Path -LiteralPath $pidPath) {
    $pidText = Get-Content -LiteralPath $pidPath -Raw -ErrorAction SilentlyContinue
    $dashboardPid = 0
    if ([int]::TryParse($pidText.Trim(), [ref]$dashboardPid)) {
        $process = Get-Process -Id $dashboardPid -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            Stop-Process -Id $dashboardPid -Force
            $stopped = $true
        }
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like 'python*.exe' -and $_.CommandLine -like "*$serverScript*"
}
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    $stopped = $true
}

if ($stopped) {
    Write-Host "Dashboard stopped on port $Port."
}
else {
    Write-Host 'Dashboard was not running.'
}
