"""Uninstall the macOS LaunchAgent for the StockCollect backend."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LABEL = "com.stockcollect.backend"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def main() -> None:
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)],
        check=False,
    )
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"[deploy] uninstalled {LABEL}")


if __name__ == "__main__":
    main()
