from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import DashboardError

DEFAULTS = {
    "intervalSeconds": 10,
    "watchdogIntervalMinutes": 5,
    "restartCount": 999,
    "restartIntervalMinutes": 1,
    "autoStart": True,
}
OPERATORS = {"yd", "lt", "dx", "hsd"}


def validate_portal(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname != "10.101.2.194"
            or parsed.port != 6060
            or parsed.path != "/portal.do"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError()
    except ValueError as error:
        raise DashboardError(
            "门户须为 http(s)://10.101.2.194:6060/portal.do，保留完整查询参数。"
        ) from error
    return value


def validate_update(payload: Any, existing: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DashboardError("请求数据必须是 JSON 对象。")
    result = {}
    for name in ("account", "operator", "portalUrl", "password"):
        value = payload.get(name, "" if name == "password" else existing.get(name, ""))
        if not isinstance(value, str):
            raise DashboardError(f"{name} 必须是字符串。")
        result[name] = value if name == "password" else value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", result["account"]):
        raise DashboardError("账号只能包含字母、数字、点、下划线或连字符。")
    if result["operator"] not in OPERATORS:
        raise DashboardError("运营商只能是 yd、lt、dx 或 hsd。")
    validate_portal(result["portalUrl"])
    ranges = {
        "intervalSeconds": (5, 3600),
        "watchdogIntervalMinutes": (1, 1440),
        "restartCount": (0, 999),
        "restartIntervalMinutes": (1, 1440),
    }
    for name, (low, high) in ranges.items():
        value = payload.get(name, existing.get(name, DEFAULTS[name]))
        if type(value) is not int or not low <= value <= high:
            raise DashboardError(f"{name} 必须是 {low} 到 {high} 之间的整数。")
        result[name] = value
    result["autoStart"] = payload.get("autoStart", existing.get("autoStart", True))
    if type(result["autoStart"]) is not bool:
        raise DashboardError("自动恢复设置必须是布尔值。")
    if len(result["password"]) > 128 or (
        result["password"] and not result["password"].strip()
    ):
        raise DashboardError("密码必须包含非空白字符，最多 128 个字符。")
    if not result["password"] and not existing.get("password"):
        raise DashboardError("首次配置必须输入上网密码。")
    return result


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".htu-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ConfigStore:
    def __init__(self, directory: Path, windows: bool = False):
        self.directory = directory
        self.path = directory / (
            "campus-auto-login.json" if windows else "desktop-config.json"
        )
        self.key_path = directory / "credential.key"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            result = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(result, dict):
                raise ValueError("configuration is not an object")
            return result
        except (OSError, ValueError) as error:
            raise DashboardError("无法读取配置，请检查本机配置文件。") from error

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Encryption is local; the private key must remain with this installation.
        from cryptography.fernet import Fernet

        previous = self.load()
        result = validate_update(payload, previous)
        if result["password"]:
            if not self.key_path.exists():
                atomic_write(self.key_path, Fernet.generate_key())
            result["password"] = (
                Fernet(self.key_path.read_bytes())
                .encrypt(result["password"].encode())
                .decode()
            )
        else:
            result["password"] = previous["password"]
        atomic_write(
            self.path, json.dumps(result, ensure_ascii=False, indent=2).encode()
        )
        return result

    def password(self, config: dict[str, Any]) -> str:
        from cryptography.fernet import Fernet, InvalidToken

        try:
            return (
                Fernet(self.key_path.read_bytes())
                .decrypt(config["password"].encode())
                .decode()
            )
        except (OSError, KeyError, ValueError, InvalidToken) as error:
            raise DashboardError("无法解密密码，请在本机重新保存密码。") from error

    def summary(self) -> dict[str, Any]:
        config = self.load()
        return {
            **DEFAULTS,
            **{k: v for k, v in config.items() if k != "password"},
            "passwordConfigured": bool(config.get("password")),
        }
