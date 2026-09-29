[CmdletBinding()]
param(
    [ValidateRange(2, 30)]
    [int]$TimeoutSeconds = 6,

    [string[]]$ProbeUrls = @(
        'http://1.1.1.1/cdn-cgi/trace',
        'http://223.5.5.5/',
        'http://www.msftconnecttest.com/redirect',
        'http://connectivitycheck.gstatic.com/generate_204'
    )
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Get-ValidPortalUrl {
    param([string]$Candidate)

    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return $null
    }

    $decoded = [System.Net.WebUtility]::HtmlDecode($Candidate.Trim())
    $uri = $null
    if (-not [Uri]::TryCreate($decoded, [UriKind]::Absolute, [ref]$uri)) {
        return $null
    }
    if ($uri.Scheme -notin @('http', 'https')) {
        return $null
    }
    if ($uri.Host -ne '10.101.2.194' -or $uri.Port -ne 6060 -or $uri.AbsolutePath -ne '/portal.do') {
        return $null
    }

    return $uri.AbsoluteUri
}

foreach ($probeUrl in $ProbeUrls) {
    $bodyPath = [IO.Path]::GetTempFileName()
    try {
        $metadata = & curl.exe `
            --noproxy '*' `
            --ipv4 `
            --silent `
            --show-error `
            --connect-timeout ([string][Math]::Min(3, $TimeoutSeconds)) `
            --max-time ([string]$TimeoutSeconds) `
            --output $bodyPath `
            --write-out '%{http_code}|%{redirect_url}' `
            $probeUrl 2>$null

        if ($LASTEXITCODE -ne 0) {
            continue
        }

        $parts = ([string]$metadata).Split('|', 2)
        if ($parts.Count -eq 2) {
            $portalUrl = Get-ValidPortalUrl -Candidate $parts[1]
            if ($null -ne $portalUrl) {
                Write-Output $portalUrl
                return
            }
        }

        $body = Get-Content -LiteralPath $bodyPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($body)) {
            $match = [regex]::Match(
                $body,
                'https?://[^\s"''<>]+/portal\.do\?[^\s"''<>]+' ,
                [Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
            if ($match.Success) {
                $portalUrl = Get-ValidPortalUrl -Candidate $match.Value
                if ($null -ne $portalUrl) {
                    Write-Output $portalUrl
                    return
                }
            }
        }
    }
    catch {
        continue
    }
    finally {
        Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
    }
}

return
