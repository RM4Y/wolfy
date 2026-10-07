#!/usr/bin/env python3
"""Shell exports for the EspBar (eval'd by startup-app.sh): where Dolphin reaches Wolfy's
relay, and whether the EspBar is linked to this session's device (Wolfy > Wii > EspBar).

The relay token is the session hook token (/wolfy-config/combo.json, written by Wolfy).
The app runs in the host network namespace: Wolfy is on localhost."""
import json
import os
import shlex
import urllib.parse
import urllib.request

try:
    hook = json.load(open("/wolfy-config/combo.json")).get("hook") or {}
except (OSError, ValueError):
    hook = {}
session = os.environ.get("WOLF_SESSION_ID", "")
out = {}
if hook.get("token") and session:
    query = urllib.parse.urlencode({"session": session, "token": hook["token"]})
    url = f"http://127.0.0.1:{hook.get('port', 8420)}/api/hooks/espbar?{query}"
    try:
        info = json.load(urllib.request.urlopen(url, timeout=5))
        out = {"WOLFY_ESPBAR_ADDR": f"127.0.0.1:{info['port']}",
               "WOLFY_ESPBAR_TOKEN": hook["token"],
               "WOLFY_ESPBAR_LINKED": "1" if info.get("linked") else "0"}
    except (OSError, ValueError, KeyError):
        pass  # Wolfy unreachable: no EspBar for this session
if os.environ.get("WOLFY_CONSOLE", "0") != "0":
    out["WOLFY_NO_BLUEZ"] = "1"  # the host's Bluetooth Wii Remotes are console 1's
for key, value in out.items():
    print(f"export {key}={shlex.quote(value)}")
