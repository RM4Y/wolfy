#!/usr/bin/env python3
"""Standalone emulators of a PlayStation session, prepared at session start.

Vita3K (portable folder ~/.local/share/Vita3K, shared): settings a session needs whatever Wolfy
or the user set, written in its config.yml (top-level "key: value" lines):
no welcome dialog, no update check, games fullscreen, no Discord.
RPCS3 (~/.config/rpcs3, shared): nothing to force, games are started with --no-gui --fullscreen.
"""
import re
from pathlib import Path

HOME = Path.home()
VITA3K = HOME / ".local/share/Vita3K"
VITA3K_FORCED = {
    "show-welcome": "false",
    "check-for-updates": "false",
    "check-for-updates-mode": "0",
    "boot-apps-full-screen": "true",
    "discord-rich-presence": "false",
}


def log(msg):
    print(f"[ps-session-setup] {msg}", flush=True)


def set_top_level(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text().split("\n") if path.is_file() else ["---", "..."]
    todo = dict(values)
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z0-9_-]+):", line)
        if m and m.group(1) in todo:
            lines[i] = f"{m.group(1)}: {todo.pop(m.group(1))}"
    end = next((i for i, l in enumerate(lines) if l.strip() == "..."), len(lines))
    lines[end:end] = [f"{k}: {v}" for k, v in todo.items()]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    for d in (VITA3K, HOME / ".config/rpcs3"):
        if not d.is_dir():
            log(f"{d} absent (dossier non monté ?)")
    if VITA3K.is_dir():
        set_top_level(VITA3K / "config.yml", VITA3K_FORCED)
        log("Vita3K config.yml prêt")
