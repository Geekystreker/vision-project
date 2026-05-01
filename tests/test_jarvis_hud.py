from PyQt5.QtCore import Qt

from ui.jarvis_hud import JarvisHUD


def test_drive_key_map_matches_standard_motor_controls():
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_W] == "F"
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_S] == "B"
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_A] == "L"
    assert JarvisHUD.DRIVE_KEY_MAP[Qt.Key_D] == "R"


def test_connection_labels_format_connected_udp_links():
    motor_chip, _ = JarvisHUD.connection_labels("motor", "CONNECTED")
    servo_chip, _ = JarvisHUD.connection_labels("servo", "CONNECTED")
    camera_chip, camera_badge = JarvisHUD.connection_labels("camera", "CONNECTED")

    assert motor_chip == "MOTOR CONNECTED"
    assert servo_chip == "SERVO CONNECTED"
    assert camera_chip == "CAM CONNECTED"
    assert camera_badge == "CAM CONNECTED"
