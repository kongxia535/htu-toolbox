from __future__ import annotations

import logging
import os
import platform
import threading
import time
from pathlib import Path

from . import network, windows
from .config import ConfigStore, validate_update
from .errors import BusyError, DashboardError


class Watcher:
    """One cooperative watcher owned by the desktop service, never arbitrary PIDs."""

    def __init__(self, store: ConfigStore):
        self.store = store
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.authentication = threading.Lock()
        self.guard = threading.Lock()
        self.last_result: dict = {}
        self.next_run: float | None = None

    def running(self) -> bool:
        return (
            self.thread is not None
            and self.thread.is_alive()
            and not self.stop_event.is_set()
        )

    def start(self) -> None:
        if not self.store.load().get("password"):
            raise DashboardError("请先保存账号配置。")
        if self.running():
            return
        if self.thread is not None and self.thread.is_alive():
            raise BusyError("登录请求正在结束，请稍后启动。")
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self.loop, name="htu-watcher", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.next_run = None

    def check(self, force: bool = False) -> dict:
        if not self.authentication.acquire(blocking=False):
            raise BusyError("已有登录检测正在进行，请稍后重试。")
        try:
            config = self.store.load()
            if not config.get("password"):
                raise DashboardError("请先保存账号配置。")
            if not force and network.network_status()["online"]:
                result = {
                    "online": True,
                    "authenticated": False,
                    "message": "网络在线，无需登录。",
                }
            else:
                result = network.login(config, self.store.password(config))
            with self.guard:
                self.last_result = {**result, "time": time.time(), "ok": True}
            logging.info("%s", result["message"])
            return result
        except DashboardError as error:
            with self.guard:
                self.last_result = {
                    "ok": False,
                    "message": str(error),
                    "time": time.time(),
                }
            logging.warning("%s", error)
            raise
        finally:
            self.authentication.release()

    def loop(self) -> None:
        failures = 0
        while not self.stop_event.is_set():
            self.next_run = None
            try:
                self.check()
                failures = 0
            except BusyError:
                pass
            except DashboardError:
                failures += 1
            except Exception:
                # Do not log raw exceptions from requests or crypto implementations.
                logging.error("后台检测异常，请重新保存配置或重启服务。")
                failures += 1
            if self.stop_event.is_set():
                break
            interval = self.store.load().get("intervalSeconds", 10)
            delay = min(
                max(interval, interval * 2 ** min(max(failures - 1, 0), 3)),
                max(interval, 60),
            )
            self.next_run = time.time() + delay
            self.stop_event.wait(delay)
        self.next_run = None

    def status(self) -> dict:
        with self.guard:
            result = dict(self.last_result)
        configured = bool(self.store.load().get("password"))
        running = self.running()
        return {
            "ok": True,
            "state": (
                "Running" if running else "Ready" if configured else "NotInstalled"
            ),
            "watcherCount": int(running),
            "processIds": [os.getpid()] if running else [],
            "nextRunTime": self.next_run,
            "lastRunTime": result.get("time"),
            "lastResult": result,
            "stopping": bool(self.thread and self.thread.is_alive() and not running),
        }


class Controller:
    def __init__(self, directory: Path, system: str | None = None):
        self.system = system or platform.system()
        self.is_windows = self.system == "Windows"
        self.store = ConfigStore(directory, windows=self.is_windows)
        self.watcher = Watcher(self.store)
        self.operations = threading.Lock()

    def platform_info(self) -> dict:
        name = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(
            self.system, self.system
        )
        return {
            "name": name,
            "backend": "scheduled-task" if self.is_windows else "local-service",
            "passwordStorage": "Windows DPAPI" if self.is_windows else "本机加密文件",
            "autostartHint": (
                "登录 Windows 后自动运行"
                if self.is_windows
                else "服务启动时恢复；系统自启需安装用户服务"
            ),
        }

    def resume(self) -> None:
        if not self.is_windows:
            config = self.store.load()
            if config.get("password") and config.get("autoStart", True):
                self.watcher.start()

    def close(self) -> None:
        if not self.is_windows:
            self.watcher.stop()

    def status(self) -> dict:
        if self.is_windows:
            try:
                return windows.task_status()
            except DashboardError as error:
                return {
                    "ok": False,
                    "state": "Unknown",
                    "error": str(error),
                    "watcherCount": 0,
                }
        return self.watcher.status()

    def update(self, payload: dict) -> str:
        config = validate_update(payload, self.store.load())
        if self.is_windows:
            args = []
            for key, flag in (
                ("account", "Account"),
                ("operator", "Operator"),
                ("portalUrl", "PortalUrl"),
                ("intervalSeconds", "IntervalSeconds"),
                ("watchdogIntervalMinutes", "WatchdogIntervalMinutes"),
                ("restartCount", "RestartCount"),
                ("restartIntervalMinutes", "RestartIntervalMinutes"),
            ):
                args.extend(["-" + flag, str(config[key])])
            args += [
                "-ConfigPath",
                str(self.store.path),
                "-LogPath",
                str(self.store.directory / "campus-auto-login.log"),
            ]
            environment = os.environ.copy()
            environment.pop("HTU_AUTO_LOGIN_PASSWORD", None)
            if config["password"]:
                environment["HTU_AUTO_LOGIN_PASSWORD"] = config["password"]
            else:
                args.append("-PreservePassword")
            if not config["autoStart"]:
                args.append("-DisableAutoStart")
            return windows.run_powershell_script(
                windows.INSTALL_SCRIPT, args, env=environment
            )
        if (
            self.watcher.thread
            and self.watcher.thread.is_alive()
            and not self.watcher.running()
        ):
            raise BusyError("后台请求正在结束，请稍后保存。")
        self.store.save(config)
        self.watcher.start()
        return "配置已保存，自动登录已启动。"

    def action(self, action: str) -> str:
        if action not in {"start", "stop", "restart", "check", "force-login"}:
            raise DashboardError("未知操作。")
        if self.is_windows:
            if action in {"check", "force-login"}:
                args = ["-Once", "-ShowStatus", "-ConfigPath", str(self.store.path)]
                if action == "force-login":
                    args.append("-ForceLogin")
                return windows.run_powershell_script(
                    windows.WATCHER_SCRIPT, args, timeout=75
                )
            if action in {"stop", "restart"}:
                windows.run_powershell_script(
                    windows.STOP_SCRIPT, ["-TaskName", windows.TASK_NAME]
                )
            if action in {"start", "restart"}:
                windows.run_powershell(
                    "$ErrorActionPreference='Stop'; "
                    f"Enable-ScheduledTask -TaskName '{windows.TASK_NAME}' | Out-Null; "
                    f"Start-ScheduledTask -TaskName '{windows.TASK_NAME}'"
                )
            return "后台任务操作已完成。"
        if action in {"check", "force-login"}:
            return self.watcher.check(force=action == "force-login")["message"]
        if action in {"stop", "restart"}:
            self.watcher.stop()
            if action == "restart" and self.watcher.thread:
                self.watcher.thread.join(timeout=40)
        if action in {"start", "restart"}:
            self.watcher.start()
        return (
            "自动登录已启动。"
            if action != "stop"
            else "自动登录已停止；进行中的请求结束后退出。"
        )

    def mutate(self, kind: str, payload: dict) -> str:
        if not self.operations.acquire(blocking=False):
            raise BusyError("另一项操作正在执行，请稍后重试。")
        try:
            return (
                self.update(payload)
                if kind == "config"
                else self.action(payload.get("action", ""))
            )
        finally:
            self.operations.release()
