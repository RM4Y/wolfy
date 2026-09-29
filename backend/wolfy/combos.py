"""Gamepad combos of the Wolf sessions (menu / quit), one settings file per emulator.

Read live by images/common/home-combo.py in each session:
- Switch (Eden): ~/.config/eden/wolfy-home-combo.json (sessions see it as /eden-config-host)
- PlayStation (RetroArch), Steam: config/<system>/wolfy/combo.json (mounted at /wolfy-config)
"""
import json
import os
from pathlib import Path

from fastapi import HTTPException

from . import settings

DEFAULT = {"enabled": True, "modifier": "start", "button": "a",
           "quit_enabled": True, "quit_combo": "start+guide", "quit_hold": 1.0}
MODIFIERS = ("start", "guide")
BUTTONS = ("a", "b", "x", "y")
QUIT_COMBOS = ("start+guide", "back+start", "back+guide")


def path(emulator: str) -> Path:
    if emulator == "eden":
        return settings.EDEN_CONFIG.parent / "wolfy-home-combo.json"
    systems = {"retroarch": "playstation", "steam": "steam"}
    if emulator in systems:
        return Path(settings.WOLFY_HOST_DIR) / "config" / systems[emulator] / "wolfy" / "combo.json"
    raise HTTPException(404, f"Pas de combinaisons pour « {emulator} »")


def read(emulator: str) -> dict:
    """Settings as shown in the UI (without the session hook)."""
    try:
        data = {**DEFAULT, **json.loads(path(emulator).read_text())}
    except (OSError, ValueError):
        data = dict(DEFAULT)
    data.pop("hook", None)
    return data


def write(emulator: str, data: dict) -> dict:
    data = {**read(emulator), **data}
    if (data["modifier"] not in MODIFIERS or data["button"] not in BUTTONS
            or data["quit_combo"] not in QUIT_COMBOS or not 0.3 <= float(data["quit_hold"]) <= 5):
        raise HTTPException(400, "Combinaison invalide")
    data["quit_hold"] = float(data["quit_hold"])
    # sessions call Wolfy back (quit combo) with this token, through the docker gateway
    data["hook"] = {"port": settings.PUBLIC_PORT, "token": settings.hook_token()}
    p = path(emulator)
    p.parent.mkdir(parents=True, exist_ok=True)
    owner = p.parent.parent.stat()
    os.chown(p.parent, owner.st_uid, owner.st_gid)
    tmp = p.with_suffix(".wolfy-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chown(tmp, owner.st_uid, owner.st_gid)
    tmp.chmod(0o644)
    tmp.replace(p)
    return read(emulator)


def ensure_hooks() -> None:
    """Create/refresh every combo file with the current hook (token, port) at startup."""
    for emulator in ("eden", "retroarch", "steam"):
        p = path(emulator)
        if not p.parent.parent.exists():
            continue
        try:
            current = json.loads(p.read_text()).get("hook")
        except (OSError, ValueError):
            current = None
        if current != {"port": settings.PUBLIC_PORT, "token": settings.hook_token()}:
            write(emulator, {})
