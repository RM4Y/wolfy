#!/usr/bin/env python3
"""Players 1-4 of Eglantine set to the gamepads of the session, before each Eglantine process starts.

    pad-config.py <qt-config.ini>

wolfy-pads (same SDL as Eglantine) lists the pads in Eglantine's order with its default mapping; each
one becomes a connected Pro Controller (player 1 = first pad connected, ...), the other players up
to 4 are disconnected, so a game sees exactly the pads in hand. Eglantine finds a pad by GUID and
port, and takes it back on reconnection. Nothing changes when no pad is there (the session's pads
arrive a moment after it starts: the next game launch picks them up), or when the automatic
detection is off (Wolfy › Émulateurs › Switch: $HOME/.config/eden/wolfy/pads.json, "auto").
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PADS_BIN = os.environ.get("WOLFY_PADS_BIN", "/opt/gow/wolfy-pads")
PLAYERS = 4
BINDINGS = ["button_a", "button_b", "button_x", "button_y", "button_lstick", "button_rstick",
            "button_l", "button_r", "button_zl", "button_zr", "button_plus", "button_minus",
            "button_dleft", "button_dup", "button_dright", "button_ddown", "button_slleft",
            "button_srleft", "button_home", "button_screenshot", "button_slright",
            "button_srright", "lstick", "rstick", "motionleft", "motionright"]


def log(msg: str) -> None:
    print(f"[pad-config] {msg}", flush=True)


def enabled(cfg: Path) -> bool:
    try:
        return bool(json.loads((cfg.parent / "wolfy/pads.json").read_text()).get("auto", True))
    except (OSError, ValueError, AttributeError):
        return True


def detect() -> list[dict]:
    try:
        out = subprocess.run([PADS_BIN], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log(f"wolfy-pads failed: {e}")
        return []
    pads = []
    for line in out.splitlines():
        try:
            pads.append(json.loads(line))
        except ValueError:
            pass
    return pads


def ini_value(value) -> str:
    """A value as Eglantine writes it (QSettings ini)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    value = str(value)
    if value == "":
        return "[empty]"
    return f'"{value}"' if any(c in value for c in ',;="') else value


def set_keys(lines: list[str], section: str, values: dict[str, str]) -> list[str]:
    """Each key = value (and key\\default=false) in section, in place, else after its header."""
    header = f"[{section}]"
    if header not in lines:
        lines += ["", header]
    out, current, todo = [], None, dict(values)
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        if current == section and "=" in line:
            key = line.split("=", 1)[0]
            name = key[:-len("\\default")] if key.endswith("\\default") else key
            if name in values:
                if name in todo:
                    out += [f"{name}\\default=false", f"{name}={todo.pop(name)}"]
                continue
        out.append(line)
        if line == header:
            insert_at = len(out)
    rest = [x for k, v in todo.items() for x in (f"{k}\\default=false", f"{k}={v}")]
    return out[:insert_at] + rest + out[insert_at:]


def main(cfg_path: str) -> None:
    cfg = Path(cfg_path)
    if not enabled(cfg):
        log("automatic detection off: players unchanged")
        return
    pads = detect()
    if not pads:
        log("no gamepad: players unchanged")
        return
    values = {}
    for player in range(PLAYERS):
        p = f"player_{player}_"
        pad = pads[player] if player < len(pads) else None
        values[p + "connected"] = ini_value(pad is not None)
        if pad is None:
            continue
        values[p + "type"] = "0"  # Pro Controller (docked)
        values[p + "vibration_enabled"] = "true"
        for key in BINDINGS:
            values[p + key] = ini_value(pad.get(key, ""))
        log(f"player {player + 1}: {pad.get('name')} ({pad.get('type')}, guid {pad.get('guid')}, "
            f"port {pad.get('port')}{', motion' if pad.get('motionright') else ''})")
    if len(pads) > PLAYERS:
        log(f"{len(pads) - PLAYERS} more gamepad(s) ignored")
    lines = cfg.read_text().splitlines() if cfg.exists() else []
    new = "\n".join(set_keys(lines, "Controls", values)) + "\n"
    tmp = cfg.with_name(cfg.name + ".pads")
    tmp.write_text(new)
    os.replace(tmp, cfg)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.config/eden/qt-config.ini"))
