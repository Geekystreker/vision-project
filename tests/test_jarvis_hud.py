from PyQt5.QtCore import Qt

from ui.jarvis_hud import JarvisHUD


def test_drive_key_map_matches_standard_motor_controls():
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_W] == "F"
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_S] == "B"
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_A] == "L"
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_D] == "R"
