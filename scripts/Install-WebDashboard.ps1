[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [string]$TaskName = 'HTU-CampusNet-Dashboard'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$serverScript = Join-Path $repositoryRoot 'web\server.py'
if (-not (Test-Path -LiteralPath $serverScript)) {
    throw "Dashboard server not found: $serverScript"
}

$pythonExe = (& python -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python 3 was not found in PATH.'
}
$pythonwExe = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwExe)) {
    $pythonwExe = $pythonExe
}
$arguments = '"{0}" --host 127.0.0.1 --port {1}' -f $serverScript, $Port

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$userId = '{0}\{1}' -f $env:USERDOMAIN, $env:USERNAME
$action = New-ScheduledTaskAction -Execute $pythonwExe -Argument $arguments -WorkingDirectory $repositoryRoot
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$logonTrigger.Delay = 'PT20S'
$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = 'PT0S'
$settings.RestartCount = 3
$settings.RestartInterval = 'PT1M'
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'HTU campus network local management dashboard.' `
    -Action $action `
    -Trigger @($logonTrigger, $watchdogTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$url = "http://127.0.0.1:$Port/"
Write-Host "Dashboard task installed: $TaskName"
Write-Host "Dashboard URL: $url"
