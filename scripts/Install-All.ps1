[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [switch]$Configure,
    [switch]$NoBrowser
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repositoryRoot 'runtime'
$configPath = Join-Path $runtimeDirectory 'campus-auto-login.json'
$installAutoLogin = Join-Path $PSScriptRoot 'Install-CampusNetAutoLogin.ps1'
$installDashboard = Join-Path $PSScriptRoot 'Install-WebDashboard.ps1'

if (-not (Test-Path -LiteralPath $installAutoLogin)) {
    throw "Missing installer: $installAutoLogin"
}
if (-not (Test-Path -LiteralPath $installDashboard)) {
    throw "Missing installer: $installDashboard"
}

$pythonExe = ''
try {
    $pythonExe = (& python -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
}
catch {
}
if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw '未检测到 Python 3。请先安装 Python 3，并在安装时勾选 Add Python to PATH，然后重新运行 Setup.cmd。'
}

function Get-ExistingConfig {
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Get-DetectedPortalUrl {
    try {
        $redirect = & curl.exe --noproxy '*' --silent --show-error --max-time 5 `
            --output NUL --write-out '%{redirect_url}' `
            'http://www.msftconnecttest.com/redirect' 2>$null
        if ($redirect -match '^http://[^/]+/portal\.do\?') {
            return $redirect.Trim()
        }
    }
    catch {
    }

    return ''
}

function Read-Operator {
    param([string]$Default = 'lt')

    $choices = @('yd', 'lt', 'dx', 'hsd')
    Write-Host ''
    Write-Host '请选择运营商：'
    Write-Host '  1. 中国移动 (yd)'
    Write-Host '  2. 中国联通 (lt)'
    Write-Host '  3. 中国电信 (dx)'
    Write-Host '  4. 校园本地账号 (hsd)'

    $defaultIndex = [Math]::Max(1, [Array]::IndexOf($choices, $Default) + 1)
    do {
        $selection = Read-Host "输入编号，直接回车使用默认值 $defaultIndex"
        if ([string]::IsNullOrWhiteSpace($selection)) {
            $selection = [string]$defaultIndex
        }
        $number = 0
    } while (-not [int]::TryParse($selection, [ref]$number) -or $number -lt 1 -or $number -gt 4)

    return $choices[$number - 1]
}

$existing = Get-ExistingConfig
$needsConfiguration = $Configure -or $null -eq $existing

if ($needsConfiguration) {
    $defaultAccount = if ($null -ne $existing) { [string]$existing.account } else { '' }
    $defaultOperator = if ($null -ne $existing) { [string]$existing.operator } else { 'lt' }
    $defaultPortalUrl = if ($null -ne $existing) { [string]$existing.portalUrl } else { Get-DetectedPortalUrl }

    Write-Host ''
    Write-Host '校园网自动登录一键安装'
    Write-Host '========================'

    $account = Read-Host "上网账号$(if ($defaultAccount) { " [$defaultAccount]" })"
    if ([string]::IsNullOrWhiteSpace($account)) {
        $account = $defaultAccount
    }
    if ([string]::IsNullOrWhiteSpace($account)) {
        throw '上网账号不能为空。'
    }

    $operator = Read-Operator -Default $defaultOperator
    $password = Read-Host '上网密码（输入时不显示）' -AsSecureString
    if ($password.Length -eq 0) {
        throw '上网密码不能为空。'
    }

    $portalUrl = Read-Host "校园门户完整地址$(if ($defaultPortalUrl) { ' [直接回车使用检测结果]' })"
    if ([string]::IsNullOrWhiteSpace($portalUrl)) {
        $portalUrl = $defaultPortalUrl
    }
    if ([string]::IsNullOrWhiteSpace($portalUrl)) {
        throw '未能自动检测校园门户地址，请从浏览器复制包含 portal.do 的完整网址。'
    }

    & $installAutoLogin `
        -Account $account `
        -Password $password `
        -Operator $operator `
        -PortalUrl $portalUrl `
        -IntervalSeconds 10 `
        -WatchdogIntervalMinutes 5 `
        -RestartCount 999 `
        -RestartIntervalMinutes 1
}
else {
    Write-Host '已检测到现有配置，正在保留加密密码并重新应用任务。'
    $watchdogIntervalMinutes = if ($existing.PSObject.Properties['watchdogIntervalMinutes']) { [int]$existing.watchdogIntervalMinutes } else { 5 }
    $restartCount = if ($existing.PSObject.Properties['restartCount']) { [int]$existing.restartCount } else { 999 }
    $restartIntervalMinutes = if ($existing.PSObject.Properties['restartIntervalMinutes']) { [int]$existing.restartIntervalMinutes } else { 1 }
    $autoStart = if ($existing.PSObject.Properties['autoStart']) { [bool]$existing.autoStart } else { $true }
    $installArguments = @{
        Account = [string]$existing.account
        Operator = [string]$existing.operator
        PortalUrl = [string]$existing.portalUrl
        IntervalSeconds = [int]$existing.intervalSeconds
        WatchdogIntervalMinutes = $watchdogIntervalMinutes
        RestartCount = $restartCount
        RestartIntervalMinutes = $restartIntervalMinutes
        PreservePassword = $true
    }
    if (-not $autoStart) {
        $installArguments.DisableAutoStart = $true
    }
    & $installAutoLogin @installArguments
}

& $installDashboard -Port $Port

$url = "http://127.0.0.1:$Port/"
Write-Host ''
Write-Host "安装完成：$url"
if (-not $NoBrowser) {
    Start-Process $url
}
