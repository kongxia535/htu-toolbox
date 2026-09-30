from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "web" / "static"
RUNTIME_DIR = ROOT_DIR / "runtime"
CONFIG_PATH = RUNTIME_DIR / "campus-auto-login.json"
LOG_PATH = RUNTIME_DIR / "campus-auto-login.log"
DASHBOARD_LOG_PATH = RUNTIME_DIR / "dashboard.log"
PID_PATH = RUNTIME_DIR / "dashboard.pid"
INSTALL_SCRIPT = ROOT_DIR / "scripts" / "Install-CampusNetAutoLogin.ps1"
STOP_SCRIPT = ROOT_DIR / "scripts" / "Stop-CampusNetAutoLogin.ps1"
WATCHER_SCRIPT = ROOT_DIR / "scripts" / "CampusNetAutoLogin.ps1"
DETECT_PORTAL_SCRIPT = ROOT_DIR / "scripts" / "Detect-CampusPortal.ps1"
TASK_NAME = "HTU-CampusNet-AutoLogin"
TOKEN_PLACEHOLDER = "{{HTU_TOKEN}}"
MAX_LOG_LINES = 1000
ALLOWED_OPERATORS = {"yd", "lt", "dx", "hsd"}

if os.name == "nt":
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


class DashboardError(RuntimeError):
    pass


def configure_logging() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(DASHBOARD_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])


def powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


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
        raise DashboardError(error or output or f"PowerShell exited with code {result.returncode}.")
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
    output = "\n".join(part for part in [(result.stdout or "").strip(), (result.stderr or "").strip()] if part)
    if result.returncode != 0:
        raise DashboardError(output or f"PowerShell exited with code {result.returncode}.")
    return output


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise DashboardError(f"Unable to read config: {error}") from error


def task_status() -> dict[str, Any]:
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
        $_.ProcessId -ne $PID -and $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*CampusNetAutoLogin.ps1*'
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


def read_log_tail(lines: int = 200) -> list[str]:
    if not LOG_PATH.exists():
        return []
    try:
        content = LOG_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as error:
        raise DashboardError(f"Unable to read log: {error}") from error
    return content[-max(1, min(lines, MAX_LOG_LINES)) :]


def probe_http(host: str, path: str, host_header: str) -> tuple[int, str, bytes]:
    connection = http.client.HTTPConnection(host, 80, timeout=4)
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Host": host_header,
                "User-Agent": "HTU-Toolbox-Dashboard/1.0",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        body = response.read(8192)
        return response.status, response.getheader("Location") or "", body
    finally:
        connection.close()


def network_status() -> dict[str, Any]:
    errors: list[str] = []
    try:
        status, location, body = probe_http("1.1.1.1", "/cdn-cgi/trace", "1.1.1.1")
        if status == 301 and location.startswith("https://1.1.1.1/") and b"cloudflare" in body.lower():
            return {"online": True, "probe": "Cloudflare 1.1.1.1", "errors": errors}
        errors.append(f"Cloudflare returned HTTP {status}")
    except OSError as error:
        errors.append(f"Cloudflare: {error}")

    try:
        status, _, body = probe_http("182.61.200.6", "/", "www.baidu.com")
        if status == 200 and b"STATUS OK" in body:
            return {"online": True, "probe": "Baidu direct IP", "errors": errors}
        errors.append(f"Baidu returned HTTP {status}")
    except OSError as error:
        errors.append(f"Baidu: {error}")

    try:
        status, _, _ = probe_http("223.5.5.5", "/", "223.5.5.5")
        if status == 404:
            return {"online": True, "probe": "AliDNS 223.5.5.5", "errors": errors}
        errors.append(f"AliDNS returned HTTP {status}")
    except OSError as error:
        errors.append(f"AliDNS: {error}")

    return {"online": False, "probe": "none", "errors": errors}


def detect_portal_url() -> dict[str, str]:
    output = run_powershell_script(DETECT_PORTAL_SCRIPT, [], timeout=35).strip()
    if not output:
        raise DashboardError(
            "未检测到校园门户重定向。当前网络可能已经认证，请断开认证后重试，或手动粘贴门户地址。"
        )
    portal_url = output.splitlines()[-1].strip()
    parsed = urlparse(portal_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != "10.101.2.194"
        or parsed.port != 6060
        or parsed.path != "/portal.do"
    ):
        raise DashboardError("自动检测返回了不受信任的门户地址。")
    return {"portalUrl": portal_url}


def get_status() -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        task_future = executor.submit(task_status)
        network_future = executor.submit(network_status)
        try:
            task = task_future.result()
        except DashboardError as error:
            task = {"ok": False, "state": "Unknown", "error": str(error), "watcherCount": 0, "processIds": []}
        try:
            network = network_future.result()
        except DashboardError as error:
            network = {"online": False, "probe": "none", "errors": [str(error)]}

    config = load_config()
    config_summary = {
        "account": config.get("account", ""),
        "operator": config.get("operator", ""),
        "intervalSeconds": config.get("intervalSeconds", 10),
        "watchdogIntervalMinutes": config.get("watchdogIntervalMinutes", 5),
        "restartCount": config.get("restartCount", 999),
        "restartIntervalMinutes": config.get("restartIntervalMinutes", 1),
        "autoStart": config.get("autoStart", True),
        "portalUrl": config.get("portalUrl", ""),
        "passwordConfigured": bool(config.get("password")),
    }
    return {
        "task": task,
        "network": network,
        "config": config_summary,
    }


def validate_config_update(payload: dict[str, Any]) -> dict[str, Any]:
    existing = load_config()
    account = str(payload.get("account", existing.get("account", ""))).strip()
    operator = str(payload.get("operator", existing.get("operator", ""))).strip()
    portal_url = str(payload.get("portalUrl", existing.get("portalUrl", ""))).strip()
    password = str(payload.get("password", ""))
    interval_raw = payload.get("intervalSeconds", existing.get("intervalSeconds", 10))
    watchdog_interval_raw = payload.get(
        "watchdogIntervalMinutes", existing.get("watchdogIntervalMinutes", 5)
    )
    restart_count_raw = payload.get("restartCount", existing.get("restartCount", 999))
    restart_interval_raw = payload.get(
        "restartIntervalMinutes", existing.get("restartIntervalMinutes", 1)
    )
    auto_start_raw = payload.get("autoStart", existing.get("autoStart", True))

    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", account):
        raise DashboardError("账号只能包含字母、数字、点、下划线或连字符。")
    if operator not in ALLOWED_OPERATORS:
        raise DashboardError("运营商只能是 yd、lt、dx 或 hsd。")
    if not portal_url:
        raise DashboardError("校园门户地址不能为空。")

    parsed_portal = urlparse(portal_url)
    if parsed_portal.scheme not in {"http", "https"} or not parsed_portal.hostname:
        raise DashboardError("校园门户地址格式无效。")
    try:
        if not parsed_portal.hostname.replace(".", "").isdigit():
            raise DashboardError("校园门户地址必须使用内网 IP，而不是域名。")
    except AttributeError as error:
        raise DashboardError("校园门户地址格式无效。") from error

    try:
        interval = int(interval_raw)
    except (TypeError, ValueError) as error:
        raise DashboardError("轮询间隔必须是整数。") from error
    if not 5 <= interval <= 3600:
        raise DashboardError("轮询间隔必须在 5 到 3600 秒之间。")
    try:
        watchdog_interval = int(watchdog_interval_raw)
        restart_count = int(restart_count_raw)
        restart_interval = int(restart_interval_raw)
    except (TypeError, ValueError) as error:
        raise DashboardError("看门狗和自动重启参数必须是整数。") from error
    if not 1 <= watchdog_interval <= 1440:
        raise DashboardError("看门狗间隔必须在 1 到 1440 分钟之间。")
    if not 0 <= restart_count <= 999:
        raise DashboardError("自动重启次数必须在 0 到 999 次之间。")
    if not 1 <= restart_interval <= 1440:
        raise DashboardError("自动重启间隔必须在 1 到 1440 分钟之间。")
    if not isinstance(auto_start_raw, bool):
        raise DashboardError("开机自启设置必须是布尔值。")
    if password and len(password) > 128:
        raise DashboardError("密码长度不能超过 128 个字符。")
    if not password and not existing.get("password"):
        raise DashboardError("首次配置必须输入上网密码。")

    return {
        "account": account,
        "operator": operator,
        "portalUrl": portal_url,
        "intervalSeconds": interval,
        "watchdogIntervalMinutes": watchdog_interval,
        "restartCount": restart_count,
        "restartIntervalMinutes": restart_interval,
        "autoStart": auto_start_raw,
        "password": password,
    }


def update_config(payload: dict[str, Any]) -> str:
    config = validate_config_update(payload)
    arguments = [
        "-Account",
        config["account"],
        "-Operator",
        config["operator"],
        "-PortalUrl",
        config["portalUrl"],
        "-IntervalSeconds",
        str(config["intervalSeconds"]),
        "-WatchdogIntervalMinutes",
        str(config["watchdogIntervalMinutes"]),
        "-RestartCount",
        str(config["restartCount"]),
        "-RestartIntervalMinutes",
        str(config["restartIntervalMinutes"]),
    ]
    env = os.environ.copy()
    if config["password"]:
        env["HTU_AUTO_LOGIN_PASSWORD"] = config["password"]
    else:
        arguments.append("-PreservePassword")
    if not config["autoStart"]:
        arguments.append("-DisableAutoStart")

    return run_powershell_script(INSTALL_SCRIPT, arguments, timeout=60, env=env)


def perform_action(action: str) -> str:
    if action == "start":
        run_powershell(
            f"Enable-ScheduledTask -TaskName '{TASK_NAME}' | Out-Null; "
            f"Start-ScheduledTask -TaskName '{TASK_NAME}'",
            timeout=20,
        )
        return "Campus auto-login task and watchdog started."
    if action == "stop":
        return run_powershell_script(STOP_SCRIPT, ["-TaskName", TASK_NAME], timeout=30)
    if action == "restart":
        run_powershell_script(STOP_SCRIPT, ["-TaskName", TASK_NAME], timeout=30)
        run_powershell(
            f"Enable-ScheduledTask -TaskName '{TASK_NAME}' | Out-Null; "
            f"Start-ScheduledTask -TaskName '{TASK_NAME}'",
            timeout=20,
        )
        return "Campus auto-login task restarted."
    if action == "check":
        return run_powershell_script(
            WATCHER_SCRIPT,
            ["-Once", "-ShowStatus"],
            timeout=75,
        )
    if action == "force-login":
        return run_powershell_script(
            WATCHER_SCRIPT,
            ["-Once", "-ForceLogin", "-ShowStatus"],
            timeout=75,
        )
    raise DashboardError("未知操作。")


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HTUToolboxDashboard/1.0"

    def __init__(self, *args: Any, token: str, config: ServerConfig, **kwargs: Any) -> None:
        self.token = token
        self.config = config
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.client_address[0], fmt % args)

    def _allowed_origin(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost"}:
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}

    def _require_api_access(self) -> None:
        if not self._allowed_origin():
            raise DashboardError("拒绝非本机请求。")
        if self.headers.get("X-HTU-Token") != self.token:
            raise DashboardError("页面令牌无效，请刷新页面。")

    def _send_bytes(
        self,
        status: int,
        data: bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, data, "application/json; charset=utf-8")

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self._allowed_origin():
                raise DashboardError("拒绝非本机请求。")

            if parsed.path == "/":
                index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
                index = index.replace(TOKEN_PLACEHOLDER, self.token)
                self._send_bytes(HTTPStatus.OK, index.encode("utf-8"), "text/html; charset=utf-8")
                return

            if parsed.path.startswith("/static/"):
                relative = parsed.path[len("/static/") :]
                candidate = (STATIC_DIR / relative).resolve()
                if STATIC_DIR not in candidate.parents or not candidate.is_file():
                    self._send_error_json(HTTPStatus.NOT_FOUND, "静态文件不存在。")
                    return
                content_types = {
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                }
                content_type = content_types.get(candidate.suffix.lower(), "application/octet-stream")
                self._send_bytes(HTTPStatus.OK, candidate.read_bytes(), content_type)
                return

            if parsed.path == "/api/status":
                self._require_api_access()
                self._send_json(HTTPStatus.OK, {"ok": True, "data": get_status()})
                return

            if parsed.path == "/api/detect-portal":
                self._require_api_access()
                self._send_json(HTTPStatus.OK, {"ok": True, "data": detect_portal_url()})
                return

            if parsed.path == "/api/logs":
                self._require_api_access()
                query = parse_qs(parsed.query)
                tail = int(query.get("tail", ["250"])[0])
                log_lines = read_log_tail(tail)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "data": {
                            "lines": log_lines,
                            "path": str(LOG_PATH),
                            "lastWriteTime": LOG_PATH.stat().st_mtime if LOG_PATH.exists() else None,
                        },
                    },
                )
                return

            if parsed.path == "/api/download-log":
                self._require_api_access()
                if not LOG_PATH.exists():
                    self._send_error_json(HTTPStatus.NOT_FOUND, "日志文件不存在。")
                    return
                self._send_bytes(
                    HTTPStatus.OK,
                    LOG_PATH.read_bytes(),
                    "text/plain; charset=utf-8",
                    cache_control="no-store",
                )
                return

            self._send_error_json(HTTPStatus.NOT_FOUND, "接口不存在。")
        except (DashboardError, ValueError, OSError) as error:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self._require_api_access()
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 64 * 1024:
                raise DashboardError("请求体过大。")
            raw_body = self.rfile.read(content_length)
            try:
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise DashboardError("请求数据不是有效 JSON。") from error

            if parsed.path == "/api/action":
                action = str(payload.get("action", ""))
                output = perform_action(action)
                self._send_json(HTTPStatus.OK, {"ok": True, "message": output or "操作已完成。"})
                return

            if parsed.path == "/api/config":
                output = update_config(payload)
                self._send_json(HTTPStatus.OK, {"ok": True, "message": output or "配置已更新。"})
                return

            self._send_error_json(HTTPStatus.NOT_FOUND, "接口不存在。")
        except (DashboardError, ValueError, OSError) as error:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:  # pragma: no cover - last-resort protection for the local server
            logging.exception("Unhandled dashboard request error")
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"服务器异常: {error}")


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: ServerConfig, token: str) -> None:
        handler = lambda *args, **kwargs: DashboardHandler(  # noqa: E731
            *args,
            token=token,
            config=config,
            **kwargs,
        )
        super().__init__((config.host, config.port), handler)
        self.server_config = config
        self.token = token


def write_pid_file() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="ascii")


def remove_pid_file() -> None:
    try:
        if PID_PATH.exists() and PID_PATH.read_text(encoding="ascii").strip() == str(os.getpid()):
            PID_PATH.unlink()
    except OSError:
        pass


def parse_args() -> tuple[ServerConfig, bool]:
    parser = argparse.ArgumentParser(description="HTU campus network local dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("Only loopback binding is allowed.")
    return ServerConfig(host=args.host, port=args.port), args.open_browser


def main() -> int:
    configure_logging()
    config, open_browser = parse_args()
    token = secrets.token_urlsafe(32)
    server = DashboardServer(config, token)
    write_pid_file()
    url = f"http://{config.host}:{config.port}/"
    logging.info("Dashboard listening on %s", url)

    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            logging.exception("Unable to open browser")

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logging.info("Dashboard interrupted")
    finally:
        server.server_close()
        remove_pid_file()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
