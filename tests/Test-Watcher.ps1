# Run on Windows PowerShell 5.1 without real network or scheduled tasks.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts\CampusNetAutoLogin.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw 'Watcher has PowerShell syntax errors.' }
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
        Invoke-Expression $statement.Extent.Text
    }
}
$Once = $true
$ForceLogin = $true
$ShowStatus = $false
$IntervalSeconds = 10
$ConfigPath = 'test-only'
$script:LastOnlineState = $null
function Write-AutoLoginLog { param([string]$Message) }
function Get-Config { return [pscustomobject]@{intervalSeconds=10} }
function Get-PlainPassword { param($Config) return 'test-only' }
function Invoke-CampusLogin { param($Config,$PlainPassword) throw 'Simulated authentication failure' }
$failed = $false
try { Invoke-WatcherLoop } catch { $failed = $true }
if (-not $failed) { throw 'Single-run authentication failure was reported as success.' }
function Invoke-CampusLogin { param($Config,$PlainPassword) return @{code='0'} }
function Test-InternetOnline { return $true }
Invoke-WatcherLoop
Write-Host 'PASS: single-run failure propagation and successful authentication (mocked).'
