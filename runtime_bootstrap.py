from __future__ import annotations

import os
import sys
from pathlib import Path


_BOOTSTRAP_GUARD = "VISION_SKIP_VENV_BOOTSTRAP"


def project_venv_python(project_root: Path) -> Path | None:
    scripts_dir = project_root / ".venv" / "Scripts"
    python_exe = scripts_dir / "python.exe"
    if python_exe.exists():
        return python_exe.resolve()
    return None


def ensure_project_venv(project_root: Path) -> None:
    if os.environ.get(_BOOTSTRAP_GUARD) == "1":
        return

    target_python = project_venv_python(project_root)
    if target_python is None:
        return

    current_python = Path(sys.executable).resolve()
    if current_python == target_python:
        return

    script_path = Path(sys.argv[0])
    if not script_path.is_absolute():
        script_path = (project_root / script_path).resolve()

    env = os.environ.copy()
    env[_BOOTSTRAP_GUARD] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    os.chdir(project_root)
    os.execve(str(target_python), [str(target_python), str(script_path), *sys.argv[1:]], env)
