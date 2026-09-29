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
}

$config | ConvertTo-Json | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

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
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$logonTrigger.Delay = 'PT15S'
$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$triggers = @($logonTrigger, $watchdogTrigger)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
$settings.ExecutionTimeLimit = 'PT0S'
$settings.RestartCount = 999
$settings.RestartInterval = 'PT1M'
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'HTU campus network watcher; checks every 10 seconds and logs in automatically when offline.' `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host 'Campus network auto-login task installed and started.'
Write-Host "Task:   $TaskName"
Write-Host "Config: $ConfigPath"
Write-Host "Log:    $LogPath"
Write-Host "Account: $Account@$Operator"
Write-Host "Interval: ${IntervalSeconds}s"
