[CmdletBinding()]
param(
    [string]$TaskName = 'HTU-CampusNet-AutoLogin',
    [string]$ConfigPath,
    [string]$LogPath,
    [switch]$RemoveData
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
    Write-Host "Removed scheduled task: $TaskName"
}
else {
    Write-Host "Scheduled task is not installed: $TaskName"
}

if ($RemoveData) {
    Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$LogPath.1" -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
    Write-Host 'Removed encrypted config and logs.'
}
else {
    Write-Host "Kept config: $ConfigPath"
    Write-Host "Kept log:    $LogPath"
}
