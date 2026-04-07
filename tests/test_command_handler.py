from modules.command_handler import CommandHandler


def test_parse_follow_phrase():
    assert CommandHandler.parse_local_command("follow the person ahead of you") == "FOLLOW"


def test_parse_scene_inspection_phrase():
    assert CommandHandler.parse_local_command("what's in front of you") == "INSPECT"


def test_parse_basic_drive_command():
    assert CommandHandler.parse_local_command("move forward") == "F"
