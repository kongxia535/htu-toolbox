[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [string]$TaskName = 'HTU-CampusNet-Dashboard'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task: $TaskName"
}

& (Join-Path $PSScriptRoot 'Stop-WebDashboard.ps1') -Port $Port
