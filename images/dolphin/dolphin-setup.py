#!/usr/bin/env python3
"""Session setup for the Wolf "Wii / GameCube" app (Dolphin), before Dolphin starts.

The host flatpak Dolphin config (/dolphin-config-host, read-only) is copied to this session's
~/.config/dolphin-emu, then the pads are set for Wolf:
- each Wii Remote slot is either driven by a Wolf pad (emulated Wii Remote + Nunchuk,
  "pad"), a gamepad plugged into the PC ("host", its node is given to the session by
  host-pads.py), a real Wii Remote through the host's Bluetooth ("real") or empty ("none");
- GameCube port n is driven by player n's pad (Wolf pad or PC gamepad);
- Back + Guide stops the emulation (dolphin-run.sh starts the Wii Menu again).
On Wii console 2+ (another session runs on console 1, see startup-app.sh) every player is
on a Wolf pad: the real Wii Remotes and PC gamepads stay with console 1.

Settings: /wolfy-config/dolphin.json (written by Wolfy), e.g.
    {"wiimotes": ["real", "pad", "host", "none"], "nunchuk": true,
     "host_pads": [null, null, {"sdl_name": "Xbox Series X Controller", ...}, null]}
The Wolf pads are seen by Dolphin through SDL: "SDL/<n>/Xbox One S Controller" for the
Xbox pad Wolf creates (n = order of the pads in the session).
"""
import configparser
import json
import os
import shutil
import sys
from pathlib import Path

HOST_CFG = Path("/dolphin-config-host")
CFG = Path.home() / ".config" / "dolphin-emu"
SETTINGS = Path("/wolfy-config/dolphin.json")
# player 1 on the Wolf pad, players 2-4 on real Wii Remotes (not connected = not there)
DEFAULT = {"wiimotes": ["pad", "real", "real", "real"], "nunchuk": True}
# SDL name of the Wolf Xbox pad (Wolf X-Box One (virtual) pad, 045e:02ea)
PAD = os.environ.get("DOLPHIN_PAD_NAME", "Xbox One S Controller")
SOURCES = {"none": "0", "pad": "1", "host": "1", "real": "2"}


def log(msg):
    print(f"[dolphin-setup] {msg}", file=sys.stderr, flush=True)


def settings() -> dict:
    try:
        data = {**DEFAULT, **json.loads(SETTINGS.read_text())}
    except (OSError, ValueError):
        data = dict(DEFAULT)
    slots = [s if s in SOURCES else "pad" for s in list(data["wiimotes"])[:4]]
    data["wiimotes"] = slots + ["none"] * (4 - len(slots))
    hosts = list(data.get("host_pads") or [])[:4]
    data["host_pads"] = hosts + [None] * (4 - len(hosts))
    if os.environ.get("WOLFY_CONSOLE", "0") != "0":
        # Wii console 2+ (startup-app.sh): the real Wii Remotes and PC gamepads are console
        # 1's, this session's players are on its Wolf pads
        data["wiimotes"] = ["pad" if s in ("real", "host") else s for s in data["wiimotes"]]
    for i, source in enumerate(data["wiimotes"]):  # PC gamepad not chosen yet: slot unused
        if source == "host" and not (data["host_pads"][i] or {}).get("sdl_name"):
            data["wiimotes"][i] = "none"
    return data


def ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # Dolphin keys are case-sensitive
    if path.is_file():
        cp.read(path, encoding="utf-8")
    return cp


def save(cp: configparser.ConfigParser, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for section in cp.sections():
            f.write(f"[{section}]\n")
            for k, v in cp[section].items():
                f.write(f"{k} = {v}\n")


def dev(n: int, name: str = PAD) -> str:
    return f"SDL/{n}/{name}"


def player_devices(s: dict) -> list[str | None]:
    """Dolphin device of each player driven by a pad: SDL numbers devices per name, in the
    order they are found (the Wolf pads exist before Dolphin starts, in player order)."""
    count: dict[str, int] = {}
    out = []
    for source, host in zip(s["wiimotes"], s["host_pads"]):
        if source not in ("pad", "host"):
            out.append(None)
            continue
        name = PAD if source == "pad" else host["sdl_name"]
        out.append(dev(count.get(name, 0), name))
        count[name] = count.get(name, 0) + 1
    return out


def q(name: str) -> str:
    return f"`{name}`"


def stick(prefix: str, side: str) -> dict:
    return {f"{prefix}/Up": q(f"{side} Y-"), f"{prefix}/Down": q(f"{side} Y+"),
            f"{prefix}/Left": q(f"{side} X-"), f"{prefix}/Right": q(f"{side} X+")}


DPAD = {"D-Pad/Up": q("Pad N"), "D-Pad/Down": q("Pad S"), "D-Pad/Left": q("Pad W"), "D-Pad/Right": q("Pad E")}


def wiimote(device: str, nunchuk: bool) -> dict:
    """Emulated Wii Remote on a Wolf Xbox pad: A = A, B = RT, 1 = X, 2 = Y, - = Back,
    + = Start, HOME = Guide, pointer = right stick (relative, R3 recenters), shake = B,
    swing = RB; Nunchuk: stick = left stick, C = LB, Z = LT, shake = L3."""
    m = {
        "Device": device,
        "Buttons/A": q("Button S"), "Buttons/B": q("Trigger R"),
        "Buttons/1": q("Button W"), "Buttons/2": q("Button N"),
        "Buttons/-": q("Back"), "Buttons/+": q("Start"), "Buttons/Home": q("Guide"),
        **DPAD,
        **stick("IR", "Right"),
        "IR/Relative Input": "True", "IR/Auto-Hide": "True", "IR/Recenter": q("Thumb R"),
        "Shake/X": q("Button E"), "Shake/Y": q("Button E"), "Shake/Z": q("Button E"),
        "Swing/Forward": q("Shoulder R"),
        "Rumble/Motor": q("Motor L"),
        "Extension": "Nunchuk" if nunchuk else "None",
    }
    if nunchuk:
        m.update({
            "Nunchuk/Buttons/C": q("Shoulder L"), "Nunchuk/Buttons/Z": q("Trigger L"),
            **stick("Nunchuk/Stick", "Left"),
            "Nunchuk/Shake/X": q("Thumb L"), "Nunchuk/Shake/Y": q("Thumb L"), "Nunchuk/Shake/Z": q("Thumb L"),
        })
    return m


def gcpad(device: str) -> dict:
    """GameCube pad on a Wolf Xbox pad (same button positions as the GameCube pad)."""
    return {
        "Device": device,
        "Buttons/A": q("Button S"), "Buttons/B": q("Button W"),
        "Buttons/X": q("Button E"), "Buttons/Y": q("Button N"),
        "Buttons/Z": q("Shoulder R"), "Buttons/Start": q("Start"),
        **stick("Main Stick", "Left"), **stick("C-Stick", "Right"),
        "Triggers/L": q("Trigger L"), "Triggers/R": q("Trigger R"),
        "Triggers/L-Analog": q("Trigger L"), "Triggers/R-Analog": q("Trigger R"),
        **DPAD,
        "Rumble/Motor": q("Motor L"),
    }


def main() -> int:
    s = settings()
    # session copy of the PC's config (the host keeps its own untouched)
    if CFG.exists():
        shutil.rmtree(CFG)
    CFG.mkdir(parents=True)
    if HOST_CFG.is_dir():
        for item in HOST_CFG.iterdir():
            if item.is_file() and item.suffix != ".ini":  # backups, Bluetooth passthrough state
                continue
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, CFG / item.name)
    else:
        log(f"{HOST_CFG} missing: Dolphin starts with its defaults")

    # Wii Remotes
    devices = player_devices(s)
    wm = ini(CFG / "WiimoteNew.ini")
    for i, (source, device) in enumerate(zip(s["wiimotes"], devices), 1):
        section = f"Wiimote{i}"
        wm[section] = {"Source": SOURCES[source]}
        if device:
            wm[section].update(wiimote(device, s["nunchuk"]))
    save(wm, CFG / "WiimoteNew.ini")

    # GameCube pads: port n = player n's pad (none for a real Wii Remote / empty player)
    gc = ini(CFG / "GCPadNew.ini")
    for i, device in enumerate(devices, 1):
        gc[f"GCPad{i}"] = gcpad(device) if device else {"Device": ""}
    save(gc, CFG / "GCPadNew.ini")

    # hotkeys: Back + Guide on the first pad stops the emulation (the Wii Menu restarts)
    hk = ini(CFG / "Hotkeys.ini")
    hk["Hotkeys"] = {**(dict(hk["Hotkeys"]) if hk.has_section("Hotkeys") else {}),
                     "Device": next((d for d in devices if d), dev(0)),
                     "General/Stop": f"{q('Back')} & {q('Guide')}"}
    save(hk, CFG / "Hotkeys.ini")

    main_ini = ini(CFG / "Dolphin.ini")
    def put(section, key, value):
        if not main_ini.has_section(section):
            main_ini.add_section(section)
        main_ini[section][key] = value
    put("Core", "WiimoteContinuousScanning", "True" if "real" in s["wiimotes"] else "False")
    for i in range(4):
        put("Core", f"SIDevice{i}", "6")  # GameCube standard controller in ports 1-4
    put("BluetoothPassthrough", "Enabled", "False")  # real Wii Remotes: Dolphin's own Bluetooth
    put("Display", "Fullscreen", "True")
    put("Interface", "ConfirmStop", "False")
    put("Interface", "PauseOnFocusLost", "False")
    put("Analytics", "PermissionAsked", "True")
    put("Analytics", "Enabled", "False")
    put("AutoUpdate", "UpdateTrack", "")
    save(main_ini, CFG / "Dolphin.ini")

    # no VSync in the session: the screen is Wolf's virtual output (sway -> encoder), syncing
    # to it only adds latency and judder
    gfx = ini(CFG / "GFX.ini")
    if not gfx.has_section("Hardware"):
        gfx.add_section("Hardware")
    gfx["Hardware"]["VSync"] = "False"
    save(gfx, CFG / "GFX.ini")
    log(f"players: {s['wiimotes']}, devices: {devices}, Nunchuk: {s['nunchuk']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
