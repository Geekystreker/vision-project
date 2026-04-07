from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from modules.windows_launcher import VisionTrayLauncher


def main() -> int:
    app = QApplication(sys.argv)
    launcher = VisionTrayLauncher(app, Path(__file__).resolve().parent / "main.py")
    launcher.show()
    app.aboutToQuit.connect(launcher.stop)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
