#!/usr/bin/env python3
"""Gives the Wii session the PC's own gamepads (USB / Bluetooth on the server) chosen in Wolfy.

A Wolf session only has the device nodes of its Wolf pads. This runs as root for the whole
session (started by /etc/cont-init.d/40-host-pads.sh): every second it looks for the chosen
gamepads among the host's input devices (/proc/bus/input is not namespaced) and creates
their /dev/input/eventN node in the container (removed when the pad disconnects). Dolphin's
SDL watches /dev/input (SDL_JOYSTICK_DISABLE_UDEV=1), so a pad turned on later is picked up.

Only for the session on Wii console 1 (one Dolphin at a time can read a PC gamepad).

Settings: /wolfy-config/dolphin.json, "host_pads": one entry per player (null or
{"name", "vendor", "product", "uniq", "sdl_name"}) for the players set to "host".
"""
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

SETTINGS = Path("/wolfy-config/dolphin.json")
INPUT = Path("/dev/input")
CONSOLE = Path("/tmp/wolfy-console")


def log(msg):
    print(f"[host-pads] {msg}", flush=True)


def wanted() -> list[dict]:
    # the PC gamepads go to the session on Wii console 1 only (startup-app.sh writes the
    # console of this session; not written yet = not known yet)
    try:
        if CONSOLE.read_text().strip() != "0":
            return []
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return []
    slots = data.get("wiimotes") or []
    pads = data.get("host_pads") or []
    return [p for s, p in zip(slots, pads) if s == "host" and isinstance(p, dict)]


def host_devices() -> list[dict]:
    """Input devices of the host with an event node."""
    try:
        text = Path("/proc/bus/input/devices").read_text()
    except OSError:
        return []
    out = []
    for block in text.split("\n\n"):
        ids = re.search(r"I: Bus=\w+ Vendor=(\w+) Product=(\w+)", block)
        name = re.search(r'N: Name="(.*)"', block)
        uniq = re.search(r"U: Uniq=(.*)", block)
        ev = re.search(r"H: Handlers=.*\b(event\d+)", block)
        if ids and name and ev:
            out.append({"vendor": int(ids.group(1), 16), "product": int(ids.group(2), 16),
                        "name": name.group(1), "uniq": (uniq.group(1).strip() if uniq else ""),
                        "event": ev.group(1)})
    return out


def matches(dev: dict, pad: dict) -> bool:
    return (dev["name"] == pad.get("name") and dev["vendor"] == pad.get("vendor")
            and dev["product"] == pad.get("product")
            and (not pad.get("uniq") or dev["uniq"] == pad["uniq"]))


def make_node(event: str) -> bool:
    node = INPUT / event
    try:
        major, minor = map(int, Path(f"/sys/class/input/{event}/dev").read_text().split(":"))
    except (OSError, ValueError):
        return False
    try:
        st = node.stat()
        if stat.S_ISCHR(st.st_mode) and os.major(st.st_rdev) == major and os.minor(st.st_rdev) == minor:
            return True
        node.unlink()
    except FileNotFoundError:
        pass
    # created aside then renamed: SDL (inotify) must see it only once readable
    tmp = INPUT / f".{event}.tmp"
    os.mknod(tmp, 0o666 | stat.S_IFCHR, os.makedev(major, minor))
    os.chmod(tmp, 0o666)
    os.rename(tmp, node)
    return True


def main() -> int:
    INPUT.mkdir(parents=True, exist_ok=True)
    os.umask(0)
    created: dict[str, str] = {}  # event -> pad name
    last_wanted = None
    while True:
        pads = wanted()
        if pads != last_wanted:
            log(f"PC gamepads for this session: {[p.get('sdl_name') or p.get('name') for p in pads] or 'none'}")
            last_wanted = pads
        present = {}
        for dev in host_devices():
            if any(matches(dev, p) for p in pads):
                present[dev["event"]] = dev["name"]
        for event, name in present.items():
            if event not in created and make_node(event):
                created[event] = name
                log(f"{name} connected ({event})")
        for event in [e for e in created if e not in present]:
            try:
                (INPUT / event).unlink()
            except OSError:
                pass
            log(f"{created.pop(event)} disconnected ({event})")
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
