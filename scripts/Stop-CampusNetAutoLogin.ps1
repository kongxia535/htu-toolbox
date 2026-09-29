[CmdletBinding()]
param(
    [string]$TaskName = 'HTU-CampusNet-AutoLogin'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repositoryRoot 'runtime'
$watcherScript = Join-Path $PSScriptRoot 'CampusNetAutoLogin.ps1'
$launcherScript = Join-Path $repositoryRoot 'web\launcher.py'
$childPidPath = Join-Path $runtimeDirectory 'campus-auto-login-child.pid'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task) {
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

Start-Sleep -Milliseconds 300

$watcherPattern = '-File\s+"?' + [regex]::Escape($watcherScript) + '"?'
$watcherProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'powershell.exe' -and $_.CommandLine -match $watcherPattern
}
foreach ($process in $watcherProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

$launcherProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like 'pythonw*.exe' -and $_.CommandLine -like "*$launcherScript*"
}
foreach ($process in $launcherProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath $childPidPath -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

$remaining = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'powershell.exe' -and $_.CommandLine -match $watcherPattern) -or
    ($_.Name -like 'pythonw*.exe' -and $_.CommandLine -like "*$launcherScript*")
}
if ($remaining) {
    throw "Unable to stop all campus watcher processes: $($remaining.ProcessId -join ', ')"
}

Write-Host "Campus auto-login task and watchdog stopped: $TaskName"
