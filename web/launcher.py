from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT_DIR / "runtime"
CHILD_PID_PATH = RUNTIME_DIR / "campus-auto-login-child.pid"
LAUNCHER_LOG_PATH = RUNTIME_DIR / "watcher-launcher.log"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def write_log(message: str) -> None:
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with LAUNCHER_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if not arguments:
        write_log("No child command was provided.")
        return 2

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        arguments,
        cwd=str(ROOT_DIR),
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )
    CHILD_PID_PATH.write_text(str(process.pid), encoding="ascii")

    def stop_child(_signum: int, _frame: object) -> None:
        if process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)

    try:
        return process.wait()
    finally:
        try:
            if CHILD_PID_PATH.exists() and CHILD_PID_PATH.read_text(encoding="ascii").strip() == str(process.pid):
                CHILD_PID_PATH.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
