[CmdletBinding()]
param(
    [int]$IntervalSeconds = 10,
    [string]$ConfigPath,
    [string]$LogPath,
    [switch]$Once,
    [switch]$ForceLogin,
    [switch]$ShowStatus
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
$script:CurlExe = Join-Path $env:SystemRoot 'System32\curl.exe'
$script:LastOnlineState = $null

function Write-AutoLoginLog {
    param([string]$Message)

    $line = '{0:yyyy-MM-dd HH:mm:sszzz} {1}' -f (Get-Date), $Message
    try {
        $logDirectory = Split-Path -Parent $LogPath
        if (-not (Test-Path -LiteralPath $logDirectory)) {
            New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        }

        if (Test-Path -LiteralPath $LogPath) {
            $currentLog = Get-Item -LiteralPath $LogPath
            if ($currentLog.Length -gt 5MB) {
                Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
            }
        }

        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
    catch {
        # Logging failure must never stop the watcher.
    }

    if ($ShowStatus) {
        Write-Host $line
    }
}

function Get-RequiredProperty {
    param(
        [object]$InputObject,
        [string]$Name
    )

    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "Missing required config value: $Name"
    }

    return [string]$property.Value
}

function Get-Config {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw "Config file not found: $ConfigPath"
    }

    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Get-RequiredProperty -InputObject $config -Name 'account' | Out-Null
    Get-RequiredProperty -InputObject $config -Name 'password' | Out-Null
    Get-RequiredProperty -InputObject $config -Name 'operator' | Out-Null
    Get-RequiredProperty -InputObject $config -Name 'portalUrl' | Out-Null

    return $config
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

function Get-PlainPassword {
    param([object]$Config)

    $encryptedPassword = Get-RequiredProperty -InputObject $Config -Name 'password'
    $securePassword = ConvertTo-SecureString -String $encryptedPassword
    return Convert-SecureStringToPlainText -SecureString $securePassword
}

function Invoke-CurlRequest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [string]$HostHeader = '',
        [int]$TimeoutSeconds = 5
    )

    $bodyPath = [IO.Path]::GetTempFileName()
    try {
        $arguments = @(
            '--noproxy', '*',
            '--ipv4',
            '--silent',
            '--show-error',
            '--connect-timeout', [string][Math]::Min(3, $TimeoutSeconds),
            '--max-time', [string]$TimeoutSeconds,
            '--output', $bodyPath,
            '--write-out', '%{http_code}|%{redirect_url}'
        )

        if (-not [string]::IsNullOrWhiteSpace($HostHeader)) {
            $arguments += @('--header', "Host: $HostHeader")
        }
        # Keep the authentication URL/password out of the process command line.
        $arguments += @('--config', '-')
        $curlConfig = 'url = "{0}"' -f $Url.Replace('\', '\\').Replace('"', '\"')

        $previousErrorActionPreference = $ErrorActionPreference
        try {
            # Windows PowerShell 5.1 can turn native stderr into a terminating error.
            # curl timeouts are expected while offline, so capture them as data.
            $ErrorActionPreference = 'Continue'
            $statusText = $curlConfig | & $script:CurlExe @arguments 2>&1
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($exitCode -ne 0) {
            return [pscustomobject]@{
                Success  = $false
                Status   = ''
                RedirectUrl = ''
                Body     = ''
                Error    = "curl failed with exit code $exitCode"
            }
        }

        $body = ''
        if (Test-Path -LiteralPath $bodyPath) {
            $body = [IO.File]::ReadAllText($bodyPath)
        }

        $resultParts = ([string]$statusText).Trim().Split('|', 2)
        return [pscustomobject]@{
            Success = $true
            Status  = $resultParts[0]
            RedirectUrl = $(if ($resultParts.Length -gt 1) { $resultParts[1] } else { '' })
            Body    = $body
            Error   = ''
        }
    }
    finally {
        Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-InternetOnline {
    try {
    $microsoft = Invoke-CurlRequest -Url 'http://www.msftconnecttest.com/connecttest.txt'
    if ($microsoft.Success -and $microsoft.Status -eq '200' -and
        $microsoft.Body.Trim() -eq 'Microsoft Connect Test') {
        return $true
    }
    $google = Invoke-CurlRequest -Url 'http://connectivitycheck.gstatic.com/generate_204'
    if ($google.Success -and $google.Status -eq '204' -and [string]::IsNullOrWhiteSpace($google.Body)) {
        return $true
    }

    return $false
    }
    catch {
        Write-AutoLoginLog "Network probe error: $($_.Exception.Message)"
        return $false
    }
}

function ConvertFrom-QueryString {
    param([string]$Query)

    $result = @{}
    if ([string]::IsNullOrWhiteSpace($Query)) {
        return $result
    }

    foreach ($pair in $Query.TrimStart('?').Split('&')) {
        if ([string]::IsNullOrWhiteSpace($pair)) {
            continue
        }

        $parts = $pair.Split('=', 2)
        $key = [Uri]::UnescapeDataString($parts[0].Replace('+', ' '))
        $value = ''
        if ($parts.Length -gt 1) {
            $value = [Uri]::UnescapeDataString($parts[1].Replace('+', ' '))
        }
        $result[$key] = $value
    }

    return $result
}

function ConvertTo-QueryString {
    param([hashtable]$Parameters)

    $pairs = foreach ($key in $Parameters.Keys) {
        '{0}={1}' -f [Uri]::EscapeDataString([string]$key),
            [Uri]::EscapeDataString([string]$Parameters[$key])
    }

    return ($pairs -join '&')
}

function Get-PortalUrl {
    param([object]$Config)

    $configuredUrl = Get-RequiredProperty -InputObject $Config -Name 'portalUrl'
    $probe = Invoke-CurlRequest -Url 'http://www.msftconnecttest.com/redirect' -TimeoutSeconds 5

    if ($probe.Success -and $probe.RedirectUrl -match '^http://10\.101\.2\.194:6060/portal\.do\?') {
        return $probe.RedirectUrl
    }

    return $configuredUrl
}

function Invoke-PortalConfigRequest {
    param(
        [string]$BaseUrl,
        [string]$PortalQuery
    )

    $configUrl = '{0}/PortalJsonAction.do?{1}&viewStatus=1' -f $BaseUrl, $PortalQuery
    $response = Invoke-CurlRequest -Url $configUrl -TimeoutSeconds 5
    if (-not $response.Success -or $response.Status -ne '200') {
        return $null
    }

    try {
        return $response.Body | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Invoke-CampusLogin {
    param(
        [object]$Config,
        [string]$PlainPassword
    )

    $portalUrl = Get-PortalUrl -Config $Config
    $portalUri = [Uri]$portalUrl
    if ($portalUri.Scheme -notin @('http', 'https') -or $portalUri.Host -ne '10.101.2.194' -or
        $portalUri.Port -ne 6060 -or $portalUri.AbsolutePath -ne '/portal.do' -or
        -not [string]::IsNullOrEmpty($portalUri.UserInfo) -or -not [string]::IsNullOrEmpty($portalUri.Fragment)) {
        throw 'Unsupported campus portal URL.'
    }

    $baseUrl = '{0}://{1}' -f $portalUri.Scheme, $portalUri.Authority
    $parameters = ConvertFrom-QueryString -Query $portalUri.Query
    $portalQuery = ConvertTo-QueryString -Parameters $parameters
    $portalConfig = Invoke-PortalConfigRequest -BaseUrl $baseUrl -PortalQuery $portalQuery

    if ($null -ne $portalConfig) {
        if ($null -ne $portalConfig.serverForm) {
            $parameters['wlanacIp'] = [string]$portalConfig.serverForm.serverip
            $parameters['version'] = [string]$portalConfig.serverForm.portalVer
        }
        if ($null -ne $portalConfig.portalconfig) {
            $parameters['portalpageid'] = [string]$portalConfig.portalconfig.id
            $parameters['timestamp'] = [string]$portalConfig.portalconfig.timestamp
            $parameters['uuid'] = [string]$portalConfig.portalconfig.uuid
        }
    }

    $account = Get-RequiredProperty -InputObject $Config -Name 'account'
    $operator = Get-RequiredProperty -InputObject $Config -Name 'operator'
    if ($account -notmatch '@') {
        $account = '{0}@{1}' -f $account, $operator
    }

    $parameters['userid'] = $account
    $parameters['passwd'] = $PlainPassword
    if (-not $parameters.ContainsKey('wlanuseripv6')) {
        $parameters['wlanuseripv6'] = ''
    }
    if (-not $parameters.ContainsKey('ssid')) {
        $parameters['ssid'] = ''
    }
    if (-not $parameters.ContainsKey('portaltype')) {
        $parameters['portaltype'] = '0'
    }
    if (-not $parameters.ContainsKey('hostname')) {
        $parameters['hostname'] = $env:COMPUTERNAME
    }
    if (-not $parameters.ContainsKey('validateCode')) {
        $parameters['validateCode'] = ''
    }
    if (-not $parameters.ContainsKey('bindCtrlId')) {
        $parameters['bindCtrlId'] = ''
    }

    $loginUrl = '{0}/quickauth.do?{1}' -f $baseUrl, (ConvertTo-QueryString -Parameters $parameters)
    $response = Invoke-CurlRequest -Url $loginUrl -TimeoutSeconds 8
    if (-not $response.Success) {
        throw "Login request failed: $($response.Error)"
    }
    if ($response.Status -ne '200') {
        throw "Login request returned HTTP $($response.Status)"
    }

    try {
        $loginResult = $response.Body | ConvertFrom-Json
    }
    catch {
        throw 'Login response is not valid JSON.'
    }

    if ([string]$loginResult.code -ne '0') {
        throw "Campus portal rejected login (code=$($loginResult.code)). Check account and operator."
    }

    return $loginResult
}

function Invoke-WatcherLoop {
    $configVisible = Test-Path -LiteralPath $ConfigPath
    Write-AutoLoginLog "Watcher process started; user=$env:USERDOMAIN\$env:USERNAME; cwd=$((Get-Location).Path); configVisible=$configVisible"
    $config = Get-Config
    $interval = $IntervalSeconds
    if ($config.PSObject.Properties['intervalSeconds'] -and [int]$config.intervalSeconds -gt 0) {
        $interval = [int]$config.intervalSeconds
    }

    Write-AutoLoginLog "Watcher started; interval=${interval}s; config=$ConfigPath"

    $failedLoginCount = 0
    $hashProvider = [Security.Cryptography.SHA256]::Create()
    try {
        $configIdentity = [BitConverter]::ToString($hashProvider.ComputeHash([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($ConfigPath).ToLowerInvariant()))).Replace('-', '')
    }
    finally { $hashProvider.Dispose() }
    $loginMutex = New-Object System.Threading.Mutex -ArgumentList $false, ('Local\HTU-CampusLogin-' + $configIdentity)
    try {
    while ($true) {
        $iterationSucceeded = $true
        $sleepSeconds = $interval
        try {
            $online = if ($ForceLogin) { $false } else { Test-InternetOnline }
            if ($online) {
                if ($script:LastOnlineState -ne $true) {
                    Write-AutoLoginLog 'Network is online; no login needed.'
                }
                $script:LastOnlineState = $true
                $failedLoginCount = 0
            }
            else {
                if ($script:LastOnlineState -ne $false) {
                    Write-AutoLoginLog 'Network is offline or captive portal detected; attempting login.'
                }
                $script:LastOnlineState = $false

                try {
                    $ownsMutex = $false
                    try { $ownsMutex = $loginMutex.WaitOne(0) }
                    catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
                    if (-not $ownsMutex) {
                        throw 'Another login request is running. Try again shortly.'
                    }
                    try {
                    $plainPassword = Get-PlainPassword -Config $config
                    try {
                        Invoke-CampusLogin -Config $config -PlainPassword $plainPassword | Out-Null
                        Write-AutoLoginLog 'Campus login request succeeded.'
                        if (Test-InternetOnline) {
                            Write-AutoLoginLog 'Internet connectivity verified.'
                        }
                        else {
                            Write-AutoLoginLog 'Authentication accepted; Internet verification is pending.'
                        }
                        $failedLoginCount = 0
                    }
                    finally {
                        $plainPassword = $null
                    }
                    }
                    finally { $loginMutex.ReleaseMutex() }
                }
                catch {
                    $iterationSucceeded = $false
                    Write-AutoLoginLog "Login attempt failed: $($_.Exception.Message)"
                    $failedLoginCount++
                    $backoffLevel = [Math]::Min($failedLoginCount, 3)
                    $sleepSeconds = [int][Math]::Min(60, $interval * [Math]::Pow(2, $backoffLevel - 1))
                }
            }
        }
        catch {
            $iterationSucceeded = $false
            Write-AutoLoginLog "Watcher iteration failed but will continue: $($_.Exception.Message)"
        }

        if ($Once) {
            if (-not $iterationSucceeded) {
                throw 'Login check failed. See the log for the result.'
            }
            break
        }

        Start-Sleep -Seconds $sleepSeconds
    }
    }
    finally { $loginMutex.Dispose() }
}

try {
    Invoke-WatcherLoop
    if ($Once) {
        exit 0
    }
}
catch {
    Write-AutoLoginLog "Watcher stopped with error: $($_.Exception.Message)"
    if ($Once -or $ShowStatus) {
        Write-Error $_ -ErrorAction Continue
    }
    exit 1
}
