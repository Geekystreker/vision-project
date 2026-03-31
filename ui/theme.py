JARVIS_THEME = """
QMainWindow, QWidget {
    background-color: #000000;
    color: #87f8ff;
    font-family: "Consolas", "Orbitron", monospace;
    font-size: 12px;
}
QMainWindow {
    background: qradialgradient(
        cx: 0.52, cy: 0.48, radius: 0.95,
        fx: 0.52, fy: 0.48,
        stop: 0 #02131e,
        stop: 0.45 #010910,
        stop: 1 #000000
    );
}
QLabel#titleLabel {
    font-size: 34px;
    font-weight: 700;
    color: #b8fcff;
    letter-spacing: 2px;
}
QFrame#hudPanel {
    border: 1px solid #00bfe0;
    border-radius: 9px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #03131e,
        stop: 1 #01070d
    );
}
QFrame#corePanel {
    border: 1px solid #1ddcff;
    border-radius: 12px;
    background: qradialgradient(
        cx: 0.5, cy: 0.5, radius: 0.95,
        fx: 0.5, fy: 0.5,
        stop: 0 #082436,
        stop: 0.52 #03111b,
        stop: 1 #01070d
    );
}
QLabel#panelTitle {
    font-size: 12px;
    font-weight: 700;
    color: #9dfaff;
    letter-spacing: 1px;
}
QTextEdit#console, QLineEdit {
    border: 1px solid #00c3e8;
    border-radius: 6px;
    background-color: #01060a;
    color: #74f7ff;
    padding: 6px;
}
QPushButton {
    border: 1px solid #00c3e8;
    border-radius: 6px;
    background-color: #053849;
    color: #c3fcff;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #08607a;
}
QLabel#modeBadge {
    border: 1px solid #1adfff;
    border-radius: 11px;
    padding: 3px 14px;
    background-color: #032030;
    color: #b8feff;
    min-width: 90px;
    max-width: 120px;
}
QLabel#cameraBox {
    border: 1px solid #00c3e8;
    border-radius: 8px;
    background-color: #01050a;
    color: #5ce8ff;
    letter-spacing: 1px;
}
QLabel#statKey {
    color: #52cfdf;
    font-size: 11px;
}
QLabel#statValue {
    color: #b9fbff;
    font-size: 13px;
    font-weight: 600;
}
QStatusBar {
    border-top: 1px solid #00c3e8;
    color: #9dfbff;
    background-color: #01060c;
}
"""
