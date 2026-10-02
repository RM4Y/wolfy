"""Dolphin settings for the Wii / GameCube sessions: the PC's flatpak Dolphin config files
(Dolphin.ini, GFX.ini, RetroAchievements.ini…), described with the schema generated from the
sources (emulator_settings/dolphin.json, tools/gen_dolphin_schema.py).

Each Wolf session copies these files when it starts (images/dolphin/dolphin-setup.py) and
forces a few values: changes apply to the next sessions. Wolfy's own settings for the
sessions (Wii Remote slots, Nunchuk) are in config/wii/wolfy/dolphin.json.
"""
import json
import os
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from . import docker_ops, settings

SCHEMA_FILE = Path(__file__).parent / "emulator_settings" / "dolphin.json"
CFG = Path(settings.DOLPHIN_DIR) / "config" / "dolphin-emu"
BACKUPS = CFG / "wolfy-backups"
FILES = ("Dolphin.ini", "GFX.ini", "RetroAchievements.ini", "FreeLook.ini", "Logger.ini", "DSUClient.ini")
WOLFY_OPTIONS = Path(settings.WOLFY_HOST_DIR) / "config" / "wii" / "wolfy" / "dolphin.json"
WOLFY_DEFAULT = {"wiimotes": ["pad", "real", "real", "real"], "nunchuk": True, "host_pads": [None] * 4}
SLOT_SOURCES = ("pad", "host", "real", "none")
HOST_PAD_KEYS = ("name", "vendor", "product", "uniq", "sdl_name")
IMAGE = "wolfy-dolphin:latest"

# values the session sets on its copy (images/dolphin/dolphin-setup.py)
FORCED = {
    ("Dolphin.ini", "Display", "Fullscreen"): "True (plein écran)",
    ("Dolphin.ini", "Interface", "ConfirmStop"): "False (pas de confirmation)",
    ("Dolphin.ini", "Interface", "PauseOnFocusLost"): "False",
    ("Dolphin.ini", "Analytics", "Enabled"): "False",
    ("Dolphin.ini", "Analytics", "PermissionAsked"): "True",
    ("Dolphin.ini", "AutoUpdate", "UpdateTrack"): "vide (pas de mise à jour)",
    ("Dolphin.ini", "BluetoothPassthrough", "Enabled"): "False (vraies Wiimotes via le Bluetooth de Dolphin)",
    ("Dolphin.ini", "Core", "WiimoteContinuousScanning"): "True si un emplacement est « vraie Wiimote »",
    **{("Dolphin.ini", "Core", f"SIDevice{i}"): "6 (manette GameCube)" for i in range(4)},
    ("GFX.ini", "Hardware", "VSync"): "False (écran virtuel de Wolf : latence)",
}

PANES = {  # Qt window of the setting -> (tab, group)
    "GeneralPane.cpp": ("general", "Général"), "InterfacePane.cpp": ("interface", "Interface"),
    "OnScreenDisplayPane.cpp": ("interface", "Affichage à l'écran"), "AudioPane.cpp": ("audio", "Audio"),
    "GameCubePane.cpp": ("gamecube", "GameCube"), "TriforcePane.cpp": ("gamecube", "Triforce"),
    "WiiPane.cpp": ("wii", "Wii"), "AdvancedPane.cpp": ("advanced", "Avancé"),
    "PathPane.cpp": ("paths", "Dossiers"),
    "GeneralWidget.cpp": ("graphics", "Général"), "EnhancementsWidget.cpp": ("enhancements", "Améliorations"),
    "HacksWidget.cpp": ("hacks", "Hacks"), "AdvancedWidget.cpp": ("graphics_advanced", "Graphismes avancés"),
    "ColorCorrectionConfigWindow.cpp": ("enhancements", "Correction des couleurs"),
    "AchievementSettingsWidget.cpp": ("achievements", "RetroAchievements"),
    "FreeLookWidget.cpp": ("other", "Vue libre"),
}
TABS = [("general", "Général"), ("interface", "Interface"), ("audio", "Audio"), ("graphics", "Graphismes"),
        ("enhancements", "Améliorations"), ("hacks", "Hacks"), ("graphics_advanced", "Graphismes avancés"),
        ("gamecube", "GameCube"), ("wii", "Wii"), ("advanced", "Avancé"), ("paths", "Dossiers"),
        ("achievements", "RetroAchievements"), ("other", "Sans interface"), ("raw", "Valeurs brutes")]


@lru_cache
def schema() -> dict:
    data = json.loads(SCHEMA_FILE.read_text())
    data["by_key"] = {(s["file"], s["section"], s["key"]): s for s in data["settings"]}
    return data


# ------------------------------------------------------------------ ini files

def _read_ini(name: str) -> dict[tuple[str, str], str]:
    path = CFG / name
    out, section = {}, None
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            t = line.strip()
            if t.startswith("[") and t.endswith("]"):
                section = t[1:-1]
            elif section is not None and "=" in t and not t.startswith(("#", ";")):
                k, v = t.split("=", 1)
                out[(section, k.strip())] = v.strip()
    return out


def _write_ini(name: str, changes: dict[tuple[str, str], str | None]) -> None:
    """Set (value) or remove (None: Dolphin uses its default) keys, keeping the rest of the file."""
    path = CFG / name
    lines = path.read_text(errors="replace").splitlines() if path.is_file() else []
    # [(section or None for the preamble, [lines])]
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in lines:
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            blocks.append((t[1:-1], [line]))
        else:
            blocks[-1][1].append(line)
    todo = dict(changes)
    for sec, body in blocks:
        if sec is None:
            continue
        for i, line in enumerate(body[1:], 1):
            t = line.strip()
            if "=" in t and (sec, t.split("=", 1)[0].strip()) in todo:
                value = todo.pop((sec, t.split("=", 1)[0].strip()))
                body[i] = None if value is None else f"{t.split('=', 1)[0].strip()} = {value}"
        body[:] = [line for line in body if line is not None]
        new = [f"{k} = {v}" for (s, k), v in todo.items() if s == sec and v is not None]
        if new:
            while len(body) > 1 and not body[-1].strip():
                body.pop()
            body += new
    for sec in dict.fromkeys(s for s, _ in todo):
        new = [f"{k} = {v}" for (s, k), v in todo.items() if s == sec and v is not None]
        if new and sec not in [b[0] for b in blocks]:
            blocks.append((sec, [f"[{sec}]", *new]))
    text = "\n".join(line for _, body in blocks for line in body).strip("\n") + "\n"
    BACKUPS.mkdir(exist_ok=True)
    if path.is_file():
        shutil.copy2(path, BACKUPS / f"{name}.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    owner = CFG.stat()
    tmp = path.with_suffix(".wolfy-tmp")
    tmp.write_text(text)
    os.chown(tmp, owner.st_uid, owner.st_gid)
    tmp.chmod(0o644)
    tmp.replace(path)


def _typed(raw: str, kind: str):
    try:
        if kind == "bool":
            return raw.lower() in ("true", "1")
        if kind in ("int", "enum"):
            return int(float(raw))
        if kind == "float":
            return float(raw)
    except ValueError:
        pass
    return raw


def _encode(value, kind: str) -> str:
    if kind == "bool":
        return "True" if value in (True, "true", "True", 1) else "False"
    if kind in ("int", "enum"):
        return str(int(value))
    if kind == "float":
        return repr(float(value))
    text = str(value)
    if "\n" in text:
        raise HTTPException(400, "Retour à la ligne interdit dans une valeur")
    return text


def host_dolphin_running() -> bool:
    """The PC's Dolphin is running (it rewrites its config when it quits)."""
    for pid in (settings.HOST_ROOT / "proc").glob("[0-9]*"):
        try:
            if not (pid / "comm").read_text().strip().startswith("dolphin-emu"):
                continue
            cgroup = (pid / "cgroup").read_text()
        except OSError:
            continue
        if "docker" not in cgroup:
            return True
    return False


def _mtime() -> float:
    return max((CFG / f).stat().st_mtime for f in FILES if (CFG / f).exists())


# ------------------------------------------------------------------ settings page

def read() -> dict:
    sch = schema()
    items, seen = [], set()
    for name in FILES:
        values = _read_ini(name)
        for s in (x for x in sch["settings"] if x["file"] == name):
            loc = (s["section"], s["key"])
            seen.add((name, *loc))
            tab, group = PANES.get(s.get("pane"), ("other", None))
            raw = values.get(loc)
            items.append({
                "section": name, "key": f"{s['section']}/{s['key']}", "type": s["type"], "tab": tab,
                "value": _typed(raw, s["type"]) if raw is not None else s["default"],
                "label": s["label"] or s["key"], "help": s["help"], "default": s["default"],
                "category_label": group or f"{name} › {s['section']}", "group": None,
                "min": s.get("min"), "max": s.get("max"), "options": s.get("options"),
                "forced": FORCED.get((name, *loc)),
                "secret": "Token" in s["key"] or "Password" in s["key"],
            })
        for (sec, key), raw in values.items():  # keys Dolphin writes that the schema doesn't know
            if (name, sec, key) in seen:
                continue
            items.append({
                "section": name, "key": f"{sec}/{key}", "type": "raw", "tab": "raw", "value": raw,
                "label": key, "help": "", "default": None, "category_label": f"{name} › {sec}",
                "group": None, "min": None, "max": None, "options": None,
                "forced": FORCED.get((name, sec, key)), "secret": False,
            })
    return {
        "path": str(CFG),
        "description": "Configuration du Dolphin du PC (flatpak Better Wii Menu DE) : copiée au démarrage de chaque "
                       "session Wii, qui impose quelques valeurs (🔒). Les changements s'appliquent aux prochaines "
                       "sessions et au Dolphin du PC.",
        "mtime": _mtime(),
        "version": f"Dolphin Better Wii Menu DE {sch['dolphin_ref'][:10]}",
        "tabs": [{"id": t, "label": label} for t, label in TABS],
        "items": items,
        "backups": list_backups(),
        "host_running": host_dolphin_running(),
    }


def write(changes: list[dict], mtime: float | None) -> int:
    if mtime is not None and abs(_mtime() - mtime) > 1e-6:
        raise HTTPException(409, "La configuration Dolphin a été modifiée entre-temps : recharge la page.")
    if host_dolphin_running():
        raise HTTPException(409, "Dolphin est ouvert sur le PC : ferme-le d'abord (il réécrit sa config en quittant).")
    sch = schema()
    per_file: dict[str, dict[tuple[str, str], str | None]] = {}
    for ch in changes:
        name, path = ch["section"], ch["key"]
        if name not in FILES or "/" not in path:
            raise HTTPException(400, f"Réglage inconnu : {name} {path}")
        sec, key = path.split("/", 1)
        s = sch["by_key"].get((name, sec, key))
        if ch.get("reset"):
            value = None  # key removed: Dolphin uses its default
        else:
            value = ch.get("raw", ch.get("value"))
            kind = s["type"] if s else "string"
            if s and s.get("options") and kind in ("enum", "choice") \
                    and value not in [o["value"] for o in s["options"]]:
                raise HTTPException(400, f"Valeur invalide pour {key} : {value}")
            if s and kind in ("int", "float") and value is not None:
                if s.get("min") is not None and float(value) < s["min"] or \
                        s.get("max") is not None and float(value) > s["max"]:
                    raise HTTPException(400, f"{key} : valeur hors bornes ({s['min']}–{s['max']})")
            value = _encode(value, kind)
        per_file.setdefault(name, {})[(sec, key)] = value
    for name, kv in per_file.items():
        _write_ini(name, kv)
    return len(changes)


def list_backups() -> list[dict]:
    if not BACKUPS.exists():
        return []
    return [{"name": p.name, "mtime": p.stat().st_mtime}
            for p in sorted(BACKUPS.glob("*.ini.*"), key=lambda p: p.stat().st_mtime, reverse=True)][:60]


def restore(name: str) -> None:
    src = BACKUPS / name
    target = name.split(".ini.")[0] + ".ini"
    if "/" in name or not src.is_file() or target not in FILES:
        raise HTTPException(404, "Sauvegarde introuvable")
    if host_dolphin_running():
        raise HTTPException(409, "Dolphin est ouvert sur le PC : ferme-le d'abord.")
    dest = CFG / target
    if dest.is_file():
        shutil.copy2(dest, BACKUPS / f"{target}.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    owner = CFG.stat()
    shutil.copyfile(src, dest)
    os.chown(dest, owner.st_uid, owner.st_gid)


# ------------------------------------------------------------------ Wolfy options (sessions)

def read_wolfy() -> dict:
    try:
        data = {**WOLFY_DEFAULT, **json.loads(WOLFY_OPTIONS.read_text())}
    except (OSError, ValueError):
        data = dict(WOLFY_DEFAULT)
    slots = [s if s in SLOT_SOURCES else "pad" for s in list(data["wiimotes"])[:4]]
    hosts = [h if isinstance(h, dict) else None for h in list(data.get("host_pads") or [])[:4]]
    return {"wiimotes": slots + ["none"] * (4 - len(slots)), "nunchuk": bool(data["nunchuk"]),
            "host_pads": hosts + [None] * (4 - len(hosts))}


def write_wolfy(wiimotes: list[str], nunchuk: bool, host_pads: list[dict | None]) -> dict:
    if len(wiimotes) != 4 or any(s not in SLOT_SOURCES for s in wiimotes):
        raise HTTPException(400, "Emplacements de Wiimote invalides")
    host_pads = (list(host_pads) + [None] * 4)[:4]
    for i, source in enumerate(wiimotes):
        pad = host_pads[i]
        if source != "host":
            host_pads[i] = None
        elif not isinstance(pad, dict) or not pad.get("sdl_name"):
            raise HTTPException(400, f"Joueur {i + 1} : choisis la manette du PC")
        else:
            host_pads[i] = {k: pad.get(k) for k in HOST_PAD_KEYS}
    WOLFY_OPTIONS.parent.mkdir(parents=True, exist_ok=True)
    tmp = WOLFY_OPTIONS.with_suffix(".wolfy-tmp")
    tmp.write_text(json.dumps({"wiimotes": wiimotes, "nunchuk": nunchuk, "host_pads": host_pads}, indent=2) + "\n")
    owner = WOLFY_OPTIONS.parent.parent.stat()
    os.chown(tmp, owner.st_uid, owner.st_gid)
    tmp.replace(WOLFY_OPTIONS)
    return read_wolfy()


def host_pads() -> list[dict]:
    """Gamepads plugged into the PC, named as Dolphin names them: sdl-pads (built with
    Dolphin's SDL) run in a throwaway container of the Wii image, like a session sees them.
    The Wolf pads of running sessions are left out."""
    try:
        out = docker_ops.client().containers.run(
            IMAGE, entrypoint="/opt/dolphin/bin/sdl-pads", remove=True,
            environment={"SDL_JOYSTICK_DISABLE_UDEV": "1"},
            volumes={"/dev/input": {"bind": "/dev/input", "mode": "ro"}},
            device_cgroup_rules=["c 13:* rmw"], network_mode="none")
    except Exception as exc:
        raise HTTPException(503, f"Détection des manettes impossible (image {IMAGE} construite ?) : {exc}")
    pads = []
    for line in out.decode(errors="replace").splitlines():
        try:
            pad = json.loads(line)
        except ValueError:
            continue
        if pad.get("name", "").startswith("Wolf ") or not pad.get("sdl_name"):
            continue
        pads.append({k: pad.get(k) for k in HOST_PAD_KEYS})
    return pads
