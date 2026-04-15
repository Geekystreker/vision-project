from __future__ import annotations

import os
import site
from pathlib import Path


_ONNXRUNTIME_PRELOADED = False


def preload_onnxruntime() -> bool:
    global _ONNXRUNTIME_PRELOADED
    if _ONNXRUNTIME_PRELOADED:
        return True

    try:
        if hasattr(os, "add_dll_directory"):
            candidate_paths: list[Path] = []
            for site_root in site.getsitepackages() + [site.getusersitepackages()]:
                root = Path(site_root)
                candidate_paths.extend(
                    [
                        root / "onnxruntime" / "capi",
                        root / "onnxruntime.libs",
                    ]
                )
            for path in candidate_paths:
                if path.exists():
                    try:
                        os.add_dll_directory(str(path))
                    except OSError:
                        pass

        import onnxruntime  # noqa: F401

        _ONNXRUNTIME_PRELOADED = True
        return True
    except Exception:
        return False
