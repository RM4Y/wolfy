"""Steam app (wolfy-steam image): shared Steam data, library folders, startup options.

    config/steam/data            the sessions' ~/.steam (Steam install, login, settings)
    config/steam/wolfy/steam.json   options read at session start (images/steam/steam-setup.py)
    config/steam/wolfy/combo.json   gamepad combos (combos.py)

Library folders are mounted at the same path in the sessions (read-write: Steam updates the
games) and registered in the sessions' Steam at start.
"""
import json
import os
from pathlib import Path

from fastapi import HTTPException

from . import settings, store
from .eden_paths import _chown_like, _clean, host, update_app_mounts

STEAM_DIR = f"{settings.WOLFY_HOST_DIR}/config/steam"
DATA = f"{STEAM_DIR}/data"
OPTIONS = Path(STEAM_DIR) / "wolfy" / "steam.json"
DEFAULT = {"libraries": [f"{settings.GAMES_DIR}/SteamLibrary"], "startup_mode": "bigpicture", "compositor": "sway",
           "mangohud": False, "proton_log": False, "extra_flags": ""}

# settings page (EmulatorSettings): one tab, typed items
FIELDS = [
    ("startup_mode", "choice", "Interface au démarrage",
     "Big Picture : interface TV classique. Steam Deck : la nouvelle interface « gamepadui ». Bureau : Steam normal.",
     [("bigpicture", "Big Picture"), ("gamepadui", "Interface Steam Deck"), ("desktop", "Bureau (fenêtre Steam)")]),
    ("mangohud", "bool", "Overlay de performances (MangoHud)",
     "Affiche FPS, charge CPU/GPU dans les jeux Vulkan et Proton.", None),
    ("proton_log", "bool", "Journaux Proton",
     "Écrit un journal steam-<appid>.log par jeu Proton lancé (dépannage).", None),
    ("extra_flags", "string", "Options de lancement de Steam supplémentaires",
     "Ajoutées à la ligne de commande de Steam (ex. -nochatui -nofriendsui).", None),
]


def read_options() -> dict:
    try:
        return {**DEFAULT, **json.loads(OPTIONS.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT)


def write_options(data: dict) -> dict:
    data = {**read_options(), **data}
    OPTIONS.parent.mkdir(parents=True, exist_ok=True)
    tmp = OPTIONS.with_suffix(".wolfy-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(OPTIONS)
    _chown_like(OPTIONS.parent, OPTIONS.parent.parent.parent)
    return data


# ------------------------------------------------------------------ settings page

def read() -> dict:
    opts = read_options()
    items = []
    for key, kind, label, help_, choices in FIELDS:
        items.append({
            "section": "steam.json", "key": key, "tab": "steam", "type": kind, "value": opts[key],
            "label": label, "help": help_, "default": DEFAULT[key], "category_label": "Session Steam",
            "group": None, "min": None, "max": None, "forced": None, "secret": False,
            "options": [{"value": v, "label": l} for v, l in choices] if choices else None,
        })
    return {
        "path": str(OPTIONS),
        "description": "Options appliquées au démarrage de chaque session Steam. Les réglages de Steam lui-même "
                       "(compte, contrôleurs, Proton par défaut…) se font dans Steam : ils sont partagés par tous "
                       "les appareils.",
        "version": "Steam (Games on Whales)",
        "mtime": OPTIONS.stat().st_mtime if OPTIONS.exists() else None,
        "tabs": [{"id": "steam", "label": "Session"}],
        "items": items,
        "backups": [],
    }


def write(changes: list[dict], mtime) -> int:
    fields = {f[0]: f for f in FIELDS}
    data = {}
    for ch in changes:
        if ch["section"] != "steam.json" or ch["key"] not in fields:
            raise HTTPException(400, f"Réglage inconnu : {ch['key']}")
        _, kind, _, _, choices = fields[ch["key"]]
        value = DEFAULT[ch["key"]] if ch.get("reset") else ch.get("value", ch.get("raw"))
        if kind == "bool":
            value = value in (True, "true", 1)
        elif choices and value not in [c[0] for c in choices]:
            raise HTTPException(400, f"Valeur invalide pour {ch['key']}")
        elif kind == "string":
            value = str(value or "")
        data[ch["key"]] = value
    write_options(data)
    return len(changes)


# ------------------------------------------------------------------ libraries & mounts

def normalize(path: str) -> str:
    """A library is the folder that CONTAINS steamapps: ".../SteamLibrary/steamapps" -> ".../SteamLibrary"."""
    path = _clean(path)
    if path.rstrip("/").endswith("/steamapps") and (host(path).parent / "steamapps").is_dir():
        return str(Path(path).parent)
    return path


def _session_mounts(libraries: list[str]) -> list[str]:
    return [f"{DATA}:/home/retro/.steam:rw", f"{STEAM_DIR}/wolfy:/wolfy-config:ro"] + \
        [f"{d}:{d}:rw" for d in libraries]


def status(libraries: list[str]) -> dict:
    data = host(DATA)
    # Steam's root: the data folder itself (steam.sh there), or its debian-installation
    install = next((r for r in (data, data / "debian-installation") if (r / "steam.sh").is_file()), None)
    users = []
    # Steam's data (login, libraryfolders.vdf) is ~/.steam/steam, not the install root
    login = data / "steam" / "config" / "loginusers.vdf"
    if login.is_file():
        import re
        users = re.findall(r'"PersonaName"\s+"([^"]*)"', login.read_text(errors="replace"))
    libs = []
    for d in libraries:
        if normalize(d) != _clean(d):
            libs.append({"path": d, "exists": True, "ok": False,
                         "detail": f"c'est le dossier steamapps : la bibliothèque est {normalize(d)} (corrigé à l'enregistrement)"})
            continue
        p = host(d) / "steamapps"
        manifests = list(p.glob("appmanifest_*.acf")) if p.is_dir() else []
        libs.append({"path": d, "exists": host(d).is_dir(), "ok": p.is_dir(),
                     "detail": f"{len(manifests)} jeu(x) / outil(s) installé(s)" if p.is_dir()
                     else "pas de dossier steamapps (bibliothèque Steam ?)"})
    return {
        "data": {"exists": data.is_dir(), "ok": bool(users),
                 "detail": (f"compte : {', '.join(users)}" if users else
                            "Steam installé, pas encore connecté" if install else
                            "Steam s'installera à la première session")},
        "libraries": libs,
    }


def current() -> dict:
    return {"libraries": read_options()["libraries"], "data": DATA, "games_dir": settings.GAMES_DIR}


def apply(libraries: list[str], restart_wolf) -> dict:
    libraries = list(dict.fromkeys(normalize(d) for d in libraries if d.strip()))
    for d in libraries:
        if not host(d).is_dir():
            raise HTTPException(400, f"Bibliothèque introuvable : {d}")
    for sub in ("data", "wolfy"):
        Path(STEAM_DIR, sub).mkdir(parents=True, exist_ok=True)
    _chown_like(Path(STEAM_DIR), Path(STEAM_DIR).parent)
    write_options({"libraries": libraries})
    previous = store.get("emulator_paths").get("steam", {})
    old = set(previous.get("mounts") or [])
    new = _session_mounts(libraries)
    store.put("emulator_paths", "steam", {"mounts": new})
    changed = update_app_mounts("steam", old, new, restart_wolf, "steam-bibliotheques")
    return {"libraries": libraries, "apps_updated": changed}
