from __future__ import annotations

import json
from typing import Any


def protocol_mode(config) -> str:
    return str(getattr(config, "transport_protocol", "hybrid") or "hybrid").strip().lower()


def uses_json_protocol(config) -> bool:
    return protocol_mode(config) in {"json", "hybrid"}


def uses_legacy_protocol(config) -> bool:
    return protocol_mode(config) in {"legacy", "legacy_csv", "csv", "hybrid"}


def _with_led(packet: dict[str, Any], config) -> dict[str, Any]:
    led = str(getattr(config, "status_led_color", "blue") or "").strip()
    if led:
        packet["led"] = led
    return packet


def compact_json_packet(packet: dict[str, Any]) -> str:
    return json.dumps(packet, separators=(",", ":"))


def move_packet(config, *, direction: str, left: int, right: int) -> str:
    return compact_json_packet(
        _with_led(
            {
                "cmd": "move",
                "dir": str(direction or "S").upper(),
                "left": int(left),
                "right": int(right),
            },
            config,
        )
    )


def servo_packet(config, *, pan: int | None = None, tilt: int | None = None) -> str:
    packet: dict[str, Any] = {"cmd": "move"}
    if pan is not None:
        packet["pan"] = int(pan)
    if tilt is not None:
        packet["tilt"] = int(tilt)
    return compact_json_packet(_with_led(packet, config))
