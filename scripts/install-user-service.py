"""Install an opt-in user service; never requires administrator privileges."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def systemd_quote(value: str) -> str:
    return (
        '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="安装当前用户的 HTU Connect 后台服务")
    parser.add_argument(
        "--remove", action="store_true", help="停止并移除用户服务，保留账号配置"
    )
    args = parser.parse_args()
    system = platform.system()
    python = ROOT / ".venv/bin/python"
    if not args.remove and not python.exists():
        parser.error("请先运行 bash scripts/start.sh 安装虚拟环境")
    if system == "Linux":
        destination = (
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "systemd/user/htu-connect.service"
        )
        if args.remove:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "htu-connect.service"],
                check=True,
            )
            destination.unlink(missing_ok=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                "[Unit]\nDescription=HTU Connect campus network service\nAfter=network.target\n\n[Service]\n"
                f"WorkingDirectory={systemd_quote(str(ROOT))}\nExecStart={systemd_quote(str(python))} -m web.server\n"
                "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
            )
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "htu-connect.service"],
                check=True,
            )
    elif system == "Darwin":
        destination = Path.home() / "Library/LaunchAgents/io.htu.connect.plist"
        domain = f"gui/{os.getuid()}"
        if args.remove:
            subprocess.run(
                ["launchctl", "bootout", domain, str(destination)], check=True
            )
            destination.unlink(missing_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            runtime = ROOT / "runtime"
            runtime.mkdir(mode=0o700, exist_ok=True)
            destination.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "io.htu.connect",
                        "ProgramArguments": [str(python), "-m", "web.server"],
                        "WorkingDirectory": str(ROOT),
                        "RunAtLoad": True,
                        "KeepAlive": {"SuccessfulExit": False},
                        "StandardErrorPath": str(runtime / "launch-agent.log"),
                    }
                )
            )
            subprocess.run(
                ["launchctl", "bootstrap", domain, str(destination)], check=True
            )
    else:
        parser.error("此脚本适用于 Linux/macOS；Windows 请使用 Setup.cmd")
    print("用户服务已更新；账号配置保留在项目 runtime 目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
