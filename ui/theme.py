JARVIS_THEME = """
QMainWindow, QWidget {
    background-color: #0b0d12;
    color: #f6f1e9;
    font-family: "Agency FB", "Bahnschrift SemiCondensed", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #08090c,
        stop: 0.35 #11151f,
        stop: 0.72 #150f13,
        stop: 1 #0f0b0e
    );
}
QLabel#titleLabel {
    font-size: 32px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #fff6e2;
}
QLabel#subtitleLabel {
    color: #c3ccd8;
    font-size: 12px;
    letter-spacing: 1px;
}
QFrame#panel {
    border: 1px solid rgba(184, 124, 78, 0.45);
    border-radius: 18px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(20, 25, 33, 0.96),
        stop: 1 rgba(14, 16, 22, 0.94)
    );
}
QFrame#heroPanel {
    border: 1px solid rgba(204, 145, 92, 0.62);
    border-radius: 24px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(26, 31, 42, 0.97),
        stop: 0.55 rgba(18, 21, 30, 0.96),
        stop: 1 rgba(13, 14, 20, 0.98)
    );
}
QLabel#panelTitle {
    color: #ffe6b9;
    font-size: 12px;
    letter-spacing: 1px;
    font-weight: 700;
}
QLabel#modeBadge {
    background-color: rgba(77, 24, 31, 0.94);
    border: 1px solid rgba(255, 173, 92, 0.95);
    border-radius: 12px;
    color: #fff1d6;
    padding: 6px 14px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#cameraFeed {
    border-radius: 20px;
    background-color: #050709;
    border: 1px solid rgba(247, 174, 107, 0.62);
    padding: 0;
}
QLabel#cameraHudBadge {
    padding: 6px 10px;
    border-radius: 11px;
    background-color: rgba(28, 34, 47, 0.93);
    border: 1px solid rgba(205, 148, 98, 0.46);
    color: #ffe5c0;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#cameraHudBadgeStrong {
    padding: 6px 12px;
    border-radius: 11px;
    background-color: rgba(72, 20, 28, 0.98);
    border: 1px solid rgba(255, 173, 95, 0.82);
    color: #fff2d6;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#cameraCaption {
    color: #d3c4a8;
    font-size: 11px;
    letter-spacing: 0.4px;
    background: transparent;
}
QLabel#metricKey {
    color: #d2b892;
    font-size: 11px;
    letter-spacing: 1px;
}
QLabel#metricValue {
    color: #ffe8c5;
    font-size: 16px;
    font-weight: 600;
}
QTextEdit#console {
    border: 1px solid rgba(187, 129, 84, 0.5);
    border-radius: 16px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(15, 19, 27, 0.95),
        stop: 1 rgba(9, 11, 16, 0.97)
    );
    color: #ffefda;
    padding: 8px;
}
QLineEdit {
    border: 1px solid rgba(194, 135, 89, 0.62);
    border-radius: 14px;
    background-color: rgba(11, 14, 20, 0.96);
    color: #fff0dc;
    padding: 10px 14px;
    selection-background-color: #8a3d34;
}
QPushButton {
    border-radius: 14px;
    padding: 10px 16px;
    font-weight: 700;
    letter-spacing: 1px;
    border: 1px solid rgba(220, 156, 101, 0.72);
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #5f2a28,
        stop: 1 #3e1d21
    );
    color: #ffe9c9;
}
QPushButton:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #76312f,
        stop: 1 #542328
    );
}
QPushButton:pressed {
    background-color: #2e1519;
}
QPushButton:checked {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #9c5d28,
        stop: 1 #733f1d
    );
    border-color: #ffd093;
}
QPushButton#dangerButton {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #8a1f2b,
        stop: 1 #5f1820
    );
    border-color: #ff8a93;
}
QPushButton#dangerButton:hover {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #a32635,
        stop: 1 #78202a
    );
}
QLabel#chip {
    padding: 5px 10px;
    border-radius: 12px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(41, 47, 61, 0.95),
        stop: 1 rgba(29, 33, 44, 0.95)
    );
    border: 1px solid rgba(198, 140, 92, 0.44);
    color: #ffe5c2;
}
"""
