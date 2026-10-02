[CmdletBinding()]
param(
    [string]$TaskName = 'HTU-CampusNet-AutoLogin'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repositoryRoot 'runtime'
$watcherScript = Join-Path $PSScriptRoot 'CampusNetAutoLogin.ps1'
$launcherScript = Join-Path $repositoryRoot 'web\launcher.py'
$childPidPath = Join-Path $runtimeDirectory 'campus-auto-login-child.pid'

function Get-CampusProcessTree {
    $allProcesses = @(Get-CimInstance Win32_Process)
    $watcherPattern = '-File\s+"?' + [regex]::Escape($watcherScript) + '"?(?:\s|$)'
    $launcherPattern = [regex]::Escape($launcherScript)
    $roots = @($allProcesses | Where-Object {
        (($_.Name -in @('powershell.exe', 'pwsh.exe')) -and $_.CommandLine -match $watcherPattern) -or
        (($_.Name -like 'python*.exe') -and (
            $_.CommandLine -match $launcherPattern -or $_.CommandLine -match $watcherPattern
        ))
    })

    $depthById = @{}
    $queue = New-Object 'System.Collections.Generic.Queue[object]'
    foreach ($root in $roots) {
        $processId = [int]$root.ProcessId
        if (-not $depthById.ContainsKey($processId)) {
            $depthById[$processId] = 0
            $queue.Enqueue($root)
        }
    }

    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        $parentId = [int]$parent.ProcessId
        foreach ($child in @($allProcesses | Where-Object { [int]$_.ParentProcessId -eq $parentId })) {
            $childId = [int]$child.ProcessId
            if (-not $depthById.ContainsKey($childId)) {
                $depthById[$childId] = [int]$depthById[$parentId] + 1
                $queue.Enqueue($child)
            }
        }
    }

    return @($depthById.GetEnumerator() | ForEach-Object {
        [pscustomobject]@{
            ProcessId = [int]$_.Key
            Depth = [int]$_.Value
        }
    } | Sort-Object Depth -Descending)
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task) {
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

for ($attempt = 0; $attempt -lt 3; $attempt++) {
    Start-Sleep -Milliseconds 300
    $processTree = @(Get-CampusProcessTree)
    if ($processTree.Count -eq 0) {
        break
    }
    foreach ($process in $processTree) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item -LiteralPath $childPidPath -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

$remaining = @(Get-CampusProcessTree)
if ($remaining.Count -gt 0) {
    throw "Unable to stop all campus watcher processes: $($remaining.ProcessId -join ', ')"
}

Write-Host "Campus auto-login task, watchdog, and resident process tree stopped: $TaskName"
