#!/usr/bin/env python3
"""Gamepad combos of the Wolf "Switch" sessions (set from Wolfy > Switch > Wolfy-Eden).

HOME combo: return to the Switch HOME menu.
Quit combo (held, e.g. Start+Guide 1 s): ask Wolfy to end this Moonlight session
cleanly (Wolf API sessions/stop) instead of killing Eden, since Wolf crashes when
Moonlight resumes a session whose container died.


Runs inside each Wolf "Switch" session. When the combo (Guide or Start + A/B/X/Y,
Xbox labels) is pressed then released on the session's pad, a Guide press is
injected into that same pad: Eden maps Guide to the Switch HOME button.
Injecting on release avoids Eden seeing HOME + the combo button together
(Home+A/B/X/Y are Eden hotkeys: amiibo, fullscreen, docked mode, fps limit).

Settings: /eden-config-host/wolfy-home-combo.json (host ~/.config/eden, written
by Wolfy), re-read on change, e.g. {"enabled": true, "modifier": "start", "button": "a"}

    home-combo.py                     watch the pads
    home-combo.py --patch-config INI  before Eden starts: free the Eden hotkey
                                      that a Guide combo would also trigger
"""
import json
import os
import threading
import urllib.request
import re
import select
import struct
import sys
import time

SETTINGS = os.environ.get("HOME_COMBO_SETTINGS", "/eden-config-host/wolfy-home-combo.json")
DEFAULT = {"enabled": True, "modifier": "start", "button": "a",
           "quit_enabled": True, "quit_combo": "start+guide", "quit_hold": 1.0}

BTN_SELECT, BTN_START, BTN_MODE = 314, 315, 316
QUIT_BUTTONS = {"back": BTN_SELECT, "start": BTN_START, "guide": BTN_MODE}
MODIFIERS = {"start": BTN_START, "guide": BTN_MODE}
# Xbox labels (Linux codes of the Wolf virtual pad); Eden uses Nintendo positions
BUTTONS = {"a": 304, "b": 305, "x": 307, "y": 308}
SWITCH_LETTER = {"a": "B", "b": "A", "x": "Y", "y": "X"}

EV_SYN, EV_KEY = 0, 1
EVENT = struct.Struct("llHHi")


def log(msg):
    print(f"[home-combo] {msg}", flush=True)


def load_settings():
    try:
        with open(SETTINGS) as f:
            data = {**DEFAULT, **json.load(f)}
    except (OSError, ValueError):
        data = dict(DEFAULT)
    if data["modifier"] not in MODIFIERS or data["button"] not in BUTTONS:
        data.update(modifier=DEFAULT["modifier"], button=DEFAULT["button"])
    try:
        data["quit_codes"] = {QUIT_BUTTONS[b] for b in data["quit_combo"].split("+")}
    except (KeyError, AttributeError):
        data["quit_codes"] = {BTN_START, BTN_MODE}
    return data


def gateway():
    """Docker gateway = the host, where Wolfy listens."""
    for line in open("/proc/net/route").read().splitlines()[1:]:
        f = line.split()
        if f[1] == "00000000":
            g = f[2]
            return ".".join(str(int(g[i:i + 2], 16)) for i in (6, 4, 2, 0))
    return "172.17.0.1"


def quit_session(settings):
    hook = settings.get("hook") or {}
    session = os.environ.get("WOLF_SESSION_ID", "")
    if not hook.get("token") or not session:
        log("quit: no Wolfy hook or session id, ignored")
        return
    url = f"http://{gateway()}:{hook.get('port', 8420)}/api/hooks/session-stop"
    body = json.dumps({"session_id": session, "token": hook["token"]}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            log(f"quit: session {session} stopped ({r.status})")
    except Exception as exc:
        log(f"quit: Wolfy call failed: {exc}")


def patch_config(ini_path):
    """Guide + X also reaches Eden as Home + X: clear that Eden controller hotkey."""
    s = load_settings()
    if not s["enabled"] or s["modifier"] != "guide":
        return
    hotkey = "Home+" + SWITCH_LETTER[s["button"]]
    with open(ini_path) as f:
        lines = f.read().split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"(Shortcuts\\.*\\Controller_KeySeq)=(.*)$", line)
        if m and m.group(2).strip('"') == hotkey:
            lines[i] = f"{m.group(1)}="
            # the value is only read when \default is false
            key_default = f"{m.group(1)}\\default="
            lines = [f"{m.group(1)}\\default=false" if l.startswith(key_default) else l for l in lines]
            log(f"Eden hotkey {hotkey} disabled for this session")
    with open(ini_path, "w") as f:
        f.write("\n".join(lines))


def gamepads():
    """Event nodes of joysticks present in this container (the session's pads)."""
    try:
        text = open("/proc/bus/input/devices").read()
    except OSError:
        return set()
    nodes = set()
    for block in text.split("\n\n"):
        m = re.search(r"H: Handlers=(.*)", block)
        if m and re.search(r"\bjs\d+", m.group(1)):
            ev = re.search(r"\bevent\d+", m.group(1))
            if ev and os.path.exists("/dev/input/" + ev.group(0)):
                nodes.add("/dev/input/" + ev.group(0))
    return nodes


def press_home(fd):
    for value in (1, 0):
        os.write(fd, EVENT.pack(0, 0, EV_KEY, BTN_MODE, value) + EVENT.pack(0, 0, EV_SYN, 0, 0))
        time.sleep(0.15)


def watch():
    settings, settings_mtime = load_settings(), None
    fds, held, pending = {}, {}, set()
    quit_since, quit_done = {}, set()
    last_scan = 0
    log(f"started: {settings}")
    while True:
        now = time.time()
        if now - last_scan > 2:
            last_scan = now
            try:
                mtime = os.stat(SETTINGS).st_mtime
            except OSError:
                mtime = None
            if mtime != settings_mtime:
                settings_mtime, settings = mtime, load_settings()
                log(f"settings: {settings}")
            wanted = gamepads()
            for fd, path in list(fds.items()):
                if path not in wanted:
                    os.close(fd)
                    fds.pop(fd), held.pop(fd, None), pending.discard(fd)
            for path in wanted - set(fds.values()):
                try:
                    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                except OSError as exc:
                    log(f"cannot open {path}: {exc}")
                    continue
                fds[fd], held[fd] = path, set()
                log(f"watching {path}")
        ready, _, _ = select.select(list(fds), [], [], 0.1 if quit_since else 0.5)
        modifier = MODIFIERS[settings["modifier"]]
        button = BUTTONS[settings["button"]]
        for fd in ready:
            try:
                data = os.read(fd, EVENT.size * 64)
            except OSError:
                os.close(fd)
                fds.pop(fd, None), held.pop(fd, None), pending.discard(fd)
                continue
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, typ, code, value = EVENT.unpack_from(data, i)
                if typ != EV_KEY or value not in (0, 1):
                    continue
                if code in settings["quit_codes"]:
                    (held[fd].add if value else held[fd].discard)(code)
                if code not in (modifier, button):
                    continue
                (held[fd].add if value else held[fd].discard)(code)
                if settings["enabled"] and {modifier, button} <= held[fd]:
                    pending.add(fd)
                if fd in pending and not held[fd]:
                    pending.discard(fd)
                    log(f"{settings['modifier']}+{settings['button']} -> HOME")
                    press_home(fd)
        now = time.time()
        for fd in list(fds):
            if settings["quit_enabled"] and settings["quit_codes"] <= held.get(fd, set()):
                quit_since.setdefault(fd, now)
                if fd not in quit_done and now - quit_since[fd] >= settings["quit_hold"]:
                    quit_done.add(fd)
                    log(f"{settings['quit_combo']} held -> quit session")
                    threading.Thread(target=quit_session, args=(settings,), daemon=True).start()
            else:
                quit_since.pop(fd, None)
                quit_done.discard(fd)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--patch-config":
        patch_config(sys.argv[2])
    else:
        watch()
