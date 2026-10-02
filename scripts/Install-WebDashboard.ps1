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
& $pythonExe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
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
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200 -and $response.Content -match 'HTU Connect') { $ready = $true; break }
    }
    catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw 'Dashboard did not become ready. Check runtime/campus-auto-login.log and the scheduled task.' }

$url = "http://127.0.0.1:$Port/"
Write-Host "Dashboard task installed: $TaskName"
Write-Host "Dashboard URL: $url"
