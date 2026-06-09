"""Install a macOS LaunchAgent for the StockCollect backend."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.stockcollect.backend"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def main() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as file:
        plistlib.dump(_plist(), file, sort_keys=False)

    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
        check=True,
    )
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"],
        check=True,
    )
    print(f"[deploy] installed {PLIST_PATH}")
    print(f"[deploy] label={LABEL}")
    print(f"[deploy] app_log={PROJECT_ROOT / 'logs' / 'backend' / 'backend.log'}")
    print("[deploy] launchd stdout/stderr are discarded; app logs rotate daily.")


def _plist() -> dict[str, object]:
    uvicorn_path = PROJECT_ROOT / ".venv" / "bin" / "uvicorn"
    python_path = PROJECT_ROOT / ".venv" / "bin" / "python"
    if uvicorn_path.exists():
        program_arguments = [
            str(uvicorn_path),
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-access-log",
        ]
    else:
        program_arguments = [
            str(python_path),
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-access-log",
        ]

    return {
        "Label": LABEL,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(PROJECT_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "PATH": f"{PROJECT_ROOT / '.venv' / 'bin'}:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            "KIS_WS_AUTOSTART": "true",
            "BATCH_SCHEDULER_AUTOSTART": "true",
            "ORDER_TRACKER_AUTOSTART": "true",
        },
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


if __name__ == "__main__":
    main()
