from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import QObject
from PyQt5.QtNetwork import QLocalSocket
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from config import Config, rover_config
from modules.audio_service import AudioService


class VisionTrayLauncher(QObject):
    def __init__(self, app: QApplication, main_script: Path) -> None:
        super().__init__()
        self._app = app
        self._main_script = main_script
        self._audio_service = AudioService(rover_config)
        self._audio_service.set_launch_callback(self.launch_or_activate)
        self._audio_service.set_wake_listener(True)

        icon = self._build_icon()
        self._tray = QSystemTrayIcon(icon, parent=app)
        self._tray.setToolTip(Config.LAUNCHER_APP_NAME)
        self._tray.activated.connect(self._handle_tray_activation)
        self._tray.setContextMenu(self._build_menu())
        self._update_tray_status(True)

    def show(self) -> None:
        self._tray.show()
        self._tray.showMessage(
            "V.I.S.I.O.N Launcher",
            "Wake listener is running in the tray. Double clap to open the control panel.",
            QSystemTrayIcon.Information,
            4000,
        )

    def stop(self) -> None:
        self._audio_service.stop()
        self._tray.hide()

    def launch_or_activate(self) -> None:
        socket = QLocalSocket(self)
        socket.connectToServer(Config.SINGLE_INSTANCE_SERVER)
        if socket.waitForConnected(150):
            socket.write(b"ACTIVATE")
            socket.flush()
            socket.waitForBytesWritten(150)
            socket.disconnectFromServer()
            return

        subprocess.Popen([sys.executable, str(self._main_script)], shell=False)

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        open_action = QAction("Open V.I.S.I.O.N", menu)
        open_action.triggered.connect(self.launch_or_activate)
        menu.addAction(open_action)

        self._wake_action = QAction("Clap Listener Active", menu)
        self._wake_action.setCheckable(True)
        self._wake_action.setChecked(True)
        self._wake_action.toggled.connect(self._toggle_wake_listener)
        menu.addAction(self._wake_action)

        status_action = QAction("Status: Ready in tray", menu)
        status_action.setEnabled(False)
        self._status_action = status_action
        menu.addAction(status_action)

        exit_action = QAction("Exit Launcher", menu)
        exit_action.triggered.connect(self._quit)
        menu.addAction(exit_action)
        return menu

    def _handle_tray_activation(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.launch_or_activate()

    def _quit(self) -> None:
        self.stop()
        self._app.quit()

    def _toggle_wake_listener(self, active: bool) -> None:
        self._audio_service.set_wake_listener(active)
        self._update_tray_status(active)
        self._tray.showMessage(
            "V.I.S.I.O.N Launcher",
            "Clap listener active." if active else "Clap listener paused.",
            QSystemTrayIcon.Information,
            2500,
        )

    def _update_tray_status(self, active: bool) -> None:
        if active:
            self._tray.setToolTip("V.I.S.I.O.N Launcher - clap listener active")
            if hasattr(self, "_wake_action"):
                self._wake_action.setText("Clap Listener Active")
            if hasattr(self, "_status_action"):
                self._status_action.setText("Status: Listening for double clap")
        else:
            self._tray.setToolTip("V.I.S.I.O.N Launcher - clap listener paused")
            if hasattr(self, "_wake_action"):
                self._wake_action.setText("Clap Listener Paused")
            if hasattr(self, "_status_action"):
                self._status_action.setText("Status: Clap listener paused")

    @staticmethod
    def _build_icon() -> QIcon:
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        gradient = QRadialGradient(size / 2, size / 2, size / 2 - 4)
        gradient.setColorAt(0.0, QColor(133, 226, 255, 255))
        gradient.setColorAt(0.32, QColor(59, 181, 255, 220))
        gradient.setColorAt(0.72, QColor(20, 52, 86, 235))
        gradient.setColorAt(1.0, QColor(6, 12, 22, 255))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(173, 236, 255, 230), 2))
        painter.drawEllipse(4, 4, size - 8, size - 8)

        painter.setBrush(QColor(180, 245, 255, 245))
        painter.setPen(QPen(QColor(219, 251, 255, 255), 1))
        painter.drawEllipse(22, 22, 20, 20)

        ring_pen = QPen(QColor(117, 227, 255, 220), 3)
        painter.setBrush(QColor(0, 0, 0, 0))
        painter.setPen(ring_pen)
        painter.drawEllipse(14, 14, 36, 36)

        accent_pen = QPen(QColor(226, 248, 255, 220), 2)
        painter.setPen(accent_pen)
        painter.drawArc(10, 10, 44, 44, 20 * 16, 50 * 16)
        painter.drawArc(10, 10, 44, 44, 200 * 16, 46 * 16)

        painter.end()
        return QIcon(pixmap)
