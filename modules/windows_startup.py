from __future__ import annotations

import os
import sys
from pathlib import Path


def startup_directory() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def install_launcher_startup(launcher_script: Path) -> Path | None:
    startup_dir = startup_directory()
    if startup_dir is None:
        return None
    startup_dir.mkdir(parents=True, exist_ok=True)
    script_path = startup_dir / "VISION_Launcher.cmd"
    script_path.write_text(
        f'@echo off\r\n"{sys.executable}" "{launcher_script}"\r\n',
        encoding="utf-8",
    )
    return script_path
