from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from .errors import DashboardError

ROOT_DIR = Path(__file__).resolve().parents[1]
TASK_NAME = "HTU-CampusNet-AutoLogin"
INSTALL_SCRIPT = ROOT_DIR / "scripts" / "Install-CampusNetAutoLogin.ps1"
STOP_SCRIPT = ROOT_DIR / "scripts" / "Stop-CampusNetAutoLogin.ps1"
WATCHER_SCRIPT = ROOT_DIR / "scripts" / "CampusNetAutoLogin.ps1"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )


def run_process(
    args: list[str],
    *,
    timeout: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise DashboardError(f"Command timed out after {timeout}s.") from error
    except OSError as error:
        raise DashboardError(f"Unable to run command: {error}") from error


def run_powershell(script: str, *, timeout: int = 20) -> str:
    result = run_process(
        [
            powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        timeout=timeout,
    )
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        raise DashboardError(
            error or output or f"PowerShell exited with code {result.returncode}."
        )
    return output


def run_powershell_script(
    script_path: Path,
    arguments: list[str],
    *,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> str:
    if not script_path.exists():
        raise DashboardError(f"Script not found: {script_path}")
    result = run_process(
        [
            powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *arguments,
        ],
        timeout=timeout,
        env=env,
    )
    output = "\n".join(
        part
        for part in [(result.stdout or "").strip(), (result.stderr or "").strip()]
        if part
    )
    if result.returncode != 0:
        raise DashboardError(
            output or f"PowerShell exited with code {result.returncode}."
        )
    return output


def task_status() -> dict[str, Any]:
    watcher = str(WATCHER_SCRIPT).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
try {{
    $task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
    if ($null -eq $task) {{
        [pscustomobject]@{{
            ok = $true
            state = 'NotInstalled'
            watcherCount = 0
            processIds = @()
            restartCount = 0
            restartInterval = ''
            repeatInterval = ''
            autoStart = $false
        }} | ConvertTo-Json -Compress
        return
    }}
    $info = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
    $repeatTriggers = @($task.Triggers | Where-Object {{
        -not [string]::IsNullOrWhiteSpace([string]$_.Repetition.Interval)
    }})
    $logonTriggers = @($task.Triggers | Where-Object {{
        $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger'
    }})
    $processes = @(Get-CimInstance Win32_Process | Where-Object {{
        $_.ProcessId -ne $PID -and $_.Name -eq 'powershell.exe' -and $_.CommandLine -and $_.CommandLine.Contains('{watcher}')
    }})
    [pscustomobject]@{{
        ok = $true
        state = [string]$task.State
        lastRunTime = if ($info.LastRunTime) {{ $info.LastRunTime.ToString('o') }} else {{ $null }}
        lastTaskResult = [uint32]$info.LastTaskResult
        nextRunTime = if ($info.NextRunTime) {{ $info.NextRunTime.ToString('o') }} else {{ $null }}
        watcherCount = $processes.Count
        processIds = @($processes | ForEach-Object {{ [int]$_.ProcessId }})
        restartCount = [int]$task.Settings.RestartCount
        restartInterval = [string]$task.Settings.RestartInterval
        repeatInterval = if ($repeatTriggers.Count -gt 0) {{ [string]$repeatTriggers[0].Repetition.Interval }} else {{ '' }}
        autoStart = $logonTriggers.Count -gt 0
        multipleInstances = [string]$task.Settings.MultipleInstances
    }} | ConvertTo-Json -Compress
}}
catch {{
    [pscustomobject]@{{
        ok = $false
        state = 'Unknown'
        error = $_.Exception.Message
        watcherCount = 0
        processIds = @()
    }} | ConvertTo-Json -Compress
}}
"""
    output = run_powershell(script, timeout=20)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise DashboardError(f"Unable to parse task status: {output}") from error
