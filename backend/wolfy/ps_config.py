"""Settings of the PlayStation standalone emulators: RPCS3 (PS3) and Vita3K (PS Vita), described
with the schemas generated from their sources (emulator_settings/rpcs3.json, vita3k.json,
tools/gen_ps_schema.py). Shown next to the core options on the PlayStation page (ra_config.py).

Their data folders, in the Wolfy project, are mounted in every PlayStation session:
    config/playstation/rpcs3    ~/.config/rpcs3 (config.yml, dev_hdd0, dev_flash = firmware)
    config/playstation/vita3k   Vita3K's portable folder (config.yml, fs/ux0, fs/vs0 = firmware)
A config.yml only holds the keys set so far: the emulator uses its defaults for the others.
"""
import json
import os
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import HTTPException

from . import settings
from .eden_paths import _chown_like

PS_DIR = Path(settings.WOLFY_HOST_DIR) / "config" / "playstation"
RPCS3_DIR = PS_DIR / "rpcs3"
VITA3K_DIR = PS_DIR / "vita3k"
BACKUP_DIR = PS_DIR / "wolfy-backups"
SCHEMAS = Path(__file__).parent / "emulator_settings"
EMULATORS = {
    "RPCS3": {"file": RPCS3_DIR / "config.yml", "schema": "rpcs3.json", "tab": "PS3 (RPCS3)"},
    "Vita3K": {"file": VITA3K_DIR / "config.yml", "schema": "vita3k.json", "tab": "PS Vita (Vita3K)"},
}

# French names of RPCS3's config nodes
NODES = {"Core": "Processeur (Core)", "Video": "Vidéo", "Audio": "Audio", "Input/Output": "Entrées / sorties",
         "System": "Système", "Net": "Réseau", "Savestate": "États sauvegardés", "Miscellaneous": "Divers",
         "VFS": "Système de fichiers (VFS)", "Vulkan": "Vulkan", "Performance Overlay": "Affichage des performances",
         "Shader Loading Dialog": "Fenêtre de chargement des shaders"}
# French labels of the main RPCS3 settings (the others keep RPCS3's English name)
RPCS3_LABELS = {
    "Core › PPU Decoder": "Décodeur PPU", "Core › SPU Decoder": "Décodeur SPU",
    "Core › Preferred SPU Threads": "Threads SPU préférés", "Core › SPU Block Size": "Taille des blocs SPU",
    "Core › Thread Scheduler Mode": "Ordonnanceur de threads", "Core › RSX FIFO Fetch Accuracy": "Précision FIFO RSX",
    "Video › Renderer": "Moteur de rendu", "Video › Resolution": "Résolution de sortie",
    "Video › Aspect ratio": "Format d'image", "Video › Frame limit": "Limite d'images/s",
    "Video › MSAA": "Anticrénelage (MSAA)", "Video › Shader Mode": "Mode des shaders",
    "Video › Shader Precision": "Précision des shaders", "Video › VSync Mode": "Synchronisation verticale",
    "Video › Resolution Scale": "Échelle de résolution (%)", "Video › Anisotropic Filter Override": "Filtrage anisotrope",
    "Video › Output Scaling Mode": "Mise à l'échelle de l'image", "Video › Stretch To Display Area": "Étirer à l'écran",
    "Video › Write Color Buffers": "Écrire les tampons de couleur", "Video › Multithreaded RSX": "RSX multithread",
    "Video › Enable Frame Skip": "Saut d'images", "Video › Vulkan › Adapter": "Carte graphique (Vulkan)",
    "Video › Vulkan › Asynchronous Texture Streaming": "Streaming de textures asynchrone",
    "Video › Performance Overlay › Enabled": "Afficher les performances",
    "Audio › Renderer": "Moteur audio", "Audio › Master Volume": "Volume principal",
    "Audio › Enable Buffering": "Tampon audio", "Audio › Desired Audio Buffer Duration": "Durée du tampon audio",
    "Audio › Enable Time Stretching": "Étirement temporel",
    "System › Language": "Langue de la console", "System › License Area": "Région (licence)",
    "System › Enter button assignment": "Bouton de validation",
    "Net › Internet enabled": "Internet", "Net › PSN status": "Statut PSN",
    "Miscellaneous › Show trophy popups": "Notifications de trophées",
    "Miscellaneous › Show shader compilation hint": "Indiquer la compilation des shaders",
}


@lru_cache
def schema(emulator: str) -> dict:
    return json.loads((SCHEMAS / EMULATORS[emulator]["schema"]).read_text())["settings"]


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(500, f"{path.name} illisible : {exc}")


def _get(doc: dict, path: list[str]):
    for part in path:
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def _set(doc: dict, path: list[str], value) -> None:
    for part in path[:-1]:
        doc = doc.setdefault(part, {})
    doc[path[-1]] = value


def mtime() -> float:
    return max((e["file"].stat().st_mtime for e in EMULATORS.values() if e["file"].is_file()), default=0.0)


def _base(section: str, key: str, s: dict, value) -> dict:
    return {"section": section, "key": key, "tab": f"ps_{section}", "value": value,
            "default": s.get("default"), "help": s.get("help", ""), "group": None,
            "min": s.get("min"), "max": s.get("max"), "options": None, "forced": None, "secret": False}


def items() -> list[dict]:
    out = []
    doc = _load(EMULATORS["RPCS3"]["file"])
    for key, s in schema("RPCS3").items():
        value = _get(doc, s["path"])
        item = _base("RPCS3", key, s, s.get("default") if value is None else value)
        item.update(type={"choice": "choice", "string": "raw"}.get(s["type"], s["type"]),
                    label=RPCS3_LABELS.get(key, s["label"]),
                    category_label=" › ".join(NODES.get(p, p) for p in s["path"][:-1]))
        if s["type"] == "choice":
            item["options"] = [{"value": v, "label": v} for v in s["values"]]
        out.append(item)
    doc = _load(EMULATORS["Vita3K"]["file"])
    for key, s in schema("Vita3K").items():
        value = doc.get(key)
        item = _base("Vita3K", key, s, s.get("default") if value is None else value)
        item.update(type={"string": "raw"}.get(s["type"], s["type"]), label=s["label"], category_label=s["category"])
        if s.get("choices"):
            item["options"] = s["choices"]
            item["type"] = "choice" if isinstance(s["choices"][0]["value"], str) else "enum"
        out.append(item)
    return out


def tabs() -> list[dict]:
    return [{"id": f"ps_{name}", "label": e["tab"]} for name, e in EMULATORS.items()]


def _coerce(s: dict, value):
    kind = s["type"]
    try:
        if kind == "bool":
            return value in (True, "true", 1)
        if kind == "int":
            v = int(float(value))
        elif kind == "float":
            v = float(value)
        else:
            v = str(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Valeur invalide : {value}")
    if kind in ("int", "float") and s.get("min") is not None and not s["min"] <= v <= s["max"]:
        raise HTTPException(400, f"Valeur hors limites ({s['min']}–{s['max']}) : {v}")
    if kind == "choice" and s.get("values") and v not in s["values"]:
        raise HTTPException(400, f"Valeur invalide : {v}")
    if s.get("choices") and v not in [c["value"] for c in s["choices"]]:
        raise HTTPException(400, f"Valeur invalide : {v}")
    return v


def write(section: str, changes: list[dict]) -> None:
    sch = schema(section)
    path = EMULATORS[section]["file"]
    doc = _load(path)
    for ch in changes:
        s = sch.get(ch["key"])
        if not s:
            raise HTTPException(400, f"Réglage inconnu : {ch['key']}")
        value = s.get("default") if ch.get("reset") else _coerce(s, ch.get("raw", ch.get("value")))
        if value is None:
            raise HTTPException(400, f"Pas de valeur par défaut connue pour {ch['key']}")
        if section == "RPCS3":
            _set(doc, s["path"], value)
        else:
            doc[ch["key"]] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    _chown_like(path.parent, PS_DIR)
    if path.is_file():
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(path, BACKUP_DIR / f"{section}.config.yml.{datetime.now():%Y-%m-%d_%H-%M-%S}")
        for old in sorted(BACKUP_DIR.glob(f"{section}.config.yml.*"))[:-20]:
            old.unlink()
        _chown_like(BACKUP_DIR, PS_DIR)
    tmp = path.with_suffix(".wolfy-tmp")
    tmp.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000))
    _chown_like(tmp, PS_DIR)
    tmp.replace(path)


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    return [{"name": p.name, "mtime": p.stat().st_mtime} for p in BACKUP_DIR.glob("*.config.yml.*")
            if p.name.split(".config.yml.")[0] in EMULATORS]


def restore(name: str) -> bool:
    """Restore a config.yml backup; False if the name isn't one of ours."""
    section = name.split(".config.yml.")[0]
    if section not in EMULATORS or ".config.yml." not in name:
        return False
    src = BACKUP_DIR / name
    if "/" in name or not src.is_file():
        raise HTTPException(404, "Sauvegarde introuvable")
    dest = EMULATORS[section]["file"]
    if dest.is_file():
        shutil.copy2(dest, BACKUP_DIR / f"{section}.config.yml.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    _chown_like(dest, PS_DIR)
    return True
