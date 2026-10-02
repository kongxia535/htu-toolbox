[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Account,

    [Security.SecureString]$Password,

    [switch]$PreservePassword,

    [ValidateSet('yd', 'lt', 'dx', 'hsd')]
    [string]$Operator = 'lt',

    [string]$PortalUrl = '',

    [ValidateRange(5, 3600)]
    [int]$IntervalSeconds = 10,

    [ValidateRange(1, 1440)]
    [int]$WatchdogIntervalMinutes = 5,

    [ValidateRange(0, 999)]
    [int]$RestartCount = 999,

    [ValidateRange(1, 1440)]
    [int]$RestartIntervalMinutes = 1,

    [switch]$DisableAutoStart,

    [string]$TaskName = 'HTU-CampusNet-AutoLogin',
    [string]$ConfigPath,
    [string]$LogPath
)

$runtimeDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime'
if (-not $PSBoundParameters.ContainsKey('ConfigPath')) {
    $ConfigPath = Join-Path $runtimeDirectory 'campus-auto-login.json'
}
if (-not $PSBoundParameters.ContainsKey('LogPath')) {
    $LogPath = Join-Path $runtimeDirectory 'campus-auto-login.log'
}

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($PortalUrl) -and (Test-Path -LiteralPath $ConfigPath)) {
    try {
        $existingConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($existingConfig.PSObject.Properties['portalUrl']) {
            $PortalUrl = [string]$existingConfig.portalUrl
        }
    }
    catch {
        $PortalUrl = ''
    }
}
if ([string]::IsNullOrWhiteSpace($PortalUrl)) {
    throw 'PortalUrl is required on first install. Copy the complete campus portal URL from the browser.'
}
$portalUri = $null
if (-not [Uri]::TryCreate($PortalUrl, [UriKind]::Absolute, [ref]$portalUri) -or
    $portalUri.Scheme -notin @('http', 'https') -or $portalUri.Host -ne '10.101.2.194' -or
    $portalUri.Port -ne 6060 -or $portalUri.AbsolutePath -ne '/portal.do' -or
    -not [string]::IsNullOrEmpty($portalUri.UserInfo) -or -not [string]::IsNullOrEmpty($portalUri.Fragment)) {
    throw 'PortalUrl must use the supported campus portal host, port and path.'
}

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$SecureString)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$encryptedPassword = $null
if ($PreservePassword) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw 'Cannot preserve password because the existing config was not found.'
    }

    $existingConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $existingConfig.PSObject.Properties['password']) {
        throw 'Cannot preserve password because the existing config has no password.'
    }
    $encryptedPassword = [string]$existingConfig.password
    if ([string]::IsNullOrWhiteSpace($encryptedPassword)) {
        throw 'Cannot preserve password because the existing password is empty.'
    }
}
else {
    if ($null -eq $Password -or $Password.Length -eq 0) {
        if (-not [string]::IsNullOrEmpty($env:HTU_AUTO_LOGIN_PASSWORD)) {
            $Password = ConvertTo-SecureString -String $env:HTU_AUTO_LOGIN_PASSWORD -AsPlainText -Force
            Remove-Item Env:HTU_AUTO_LOGIN_PASSWORD -ErrorAction SilentlyContinue
        }
        else {
            $Password = Read-Host -Prompt 'Campus network password' -AsSecureString
        }
    }

    if ($Password.Length -eq 0) {
        throw 'Password cannot be empty.'
    }

    $plainPassword = Convert-SecureStringToPlainText -SecureString $Password
    try {
        if ([string]::IsNullOrWhiteSpace($plainPassword)) {
            throw 'Password cannot be empty.'
        }
    }
    finally {
        $plainPassword = $null
    }

    $encryptedPassword = ConvertFrom-SecureString -SecureString $Password
}

$configDirectory = Split-Path -Parent $ConfigPath
if (-not (Test-Path -LiteralPath $configDirectory)) {
    New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
}

$config = [ordered]@{
    account         = $Account
    password        = $encryptedPassword
    operator        = $Operator
    portalUrl       = $PortalUrl
    intervalSeconds = $IntervalSeconds
    watchdogIntervalMinutes = $WatchdogIntervalMinutes
    restartCount = $RestartCount
    restartIntervalMinutes = $RestartIntervalMinutes
    autoStart = -not $DisableAutoStart.IsPresent
}

$scriptPath = Join-Path $PSScriptRoot 'CampusNetAutoLogin.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Watcher script not found: $scriptPath"
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path $repositoryRoot 'web\launcher.py'
if (-not (Test-Path -LiteralPath $launcherScript)) {
    throw "Hidden launcher not found: $launcherScript"
}

$pythonExe = (& python -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python 3 was not found in PATH.'
}
$pythonwExe = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwExe)) {
    $pythonwExe = $pythonExe
}

$powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$watcherArguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ConfigPath "{1}" -LogPath "{2}" -IntervalSeconds {3}' -f `
    $scriptPath, $ConfigPath, $LogPath, $IntervalSeconds
$actionArguments = '"{0}" -- "{1}" {2}' -f $launcherScript, $powerShellExe, $watcherArguments

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$previousTaskXml = $null
$previousTaskRunning = $false
if ($null -ne $existingTask) {
    $previousTaskXml = Export-ScheduledTask -TaskName $TaskName
    $previousTaskRunning = $existingTask.State -eq 'Running'
}

# Resolve dependencies before replacing configuration. Replace on the same volume.
$temporaryConfig = Join-Path $configDirectory ('.htu-config-' + [Guid]::NewGuid().ToString('N'))
$hadConfig = Test-Path -LiteralPath $ConfigPath
try {
    $config | ConvertTo-Json | Set-Content -LiteralPath $temporaryConfig -Encoding UTF8
    if (Test-Path -LiteralPath $ConfigPath) {
        [IO.File]::Replace($temporaryConfig, $ConfigPath, "$ConfigPath.backup")
    }
    else {
        [IO.File]::Move($temporaryConfig, $ConfigPath)
    }
}
finally {
    Remove-Item -LiteralPath $temporaryConfig -Force -ErrorAction SilentlyContinue
}

try {
if ($null -ne $existingTask) {
    $stopScript = Join-Path $PSScriptRoot 'Stop-CampusNetAutoLogin.ps1'
    if (Test-Path -LiteralPath $stopScript) {
        & $stopScript -TaskName $TaskName | Out-Null
    }
    else {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$userId = '{0}\{1}' -f $env:USERDOMAIN, $env:USERNAME
$action = New-ScheduledTaskAction -Execute $pythonwExe -Argument $actionArguments -WorkingDirectory $repositoryRoot
$triggers = @()
if (-not $DisableAutoStart) {
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $logonTrigger.Delay = 'PT15S'
    $watchdogTrigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $WatchdogIntervalMinutes)
    $triggers = @($logonTrigger, $watchdogTrigger)
}
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = 'PT0S'
$settings.RestartCount = $RestartCount
$settings.RestartInterval = [System.Xml.XmlConvert]::ToString((New-TimeSpan -Minutes $RestartIntervalMinutes))
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$registration = @{
    TaskName = $TaskName
    Description = "HTU campus network watcher; checks every $IntervalSeconds seconds and logs in automatically when offline."
    Action = $action
    Settings = $settings
    Principal = $principal
    Force = $true
}
if ($triggers.Count -gt 0) {
    $registration.Trigger = $triggers
}
Register-ScheduledTask @registration | Out-Null

Start-ScheduledTask -TaskName $TaskName
}
catch {
    $installationError = $_
    try {
        if ($hadConfig -and (Test-Path -LiteralPath "$ConfigPath.backup")) {
            [IO.File]::Replace("$ConfigPath.backup", $ConfigPath, $null)
        }
        elseif (-not $hadConfig) {
            Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
        }
        if ($previousTaskXml) {
            Register-ScheduledTask -TaskName $TaskName -Xml $previousTaskXml -Force | Out-Null
            if ($previousTaskRunning) { Start-ScheduledTask -TaskName $TaskName }
        }
        else {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
    }
    catch { Write-Warning 'Could not restore the previous task/configuration. Check the config backup and scheduled task.' }
    throw $installationError
}

Write-Host 'Campus network auto-login task installed and started.'
Write-Host "Task:   $TaskName"
Write-Host "Config: $ConfigPath"
Write-Host "Log:    $LogPath"
Write-Host "Account: $Account@$Operator"
Write-Host "Interval: ${IntervalSeconds}s"
Write-Host "Watchdog: ${WatchdogIntervalMinutes}m"
Write-Host "Restart policy: $RestartCount attempts, every ${RestartIntervalMinutes}m"
Write-Host "Start at logon: $(-not $DisableAutoStart.IsPresent)"
