"""Core options of the PlayStation sessions (Beetle PSX HW = PS1, LRPS2 = PS2, PPSSPP = PSP),
described with the schema generated from the sources (emulator_settings/retroarch.json,
tools/gen_retroarch_schema.py), and the settings of the standalone PS3 / PS Vita emulators
(ps_config.py). RetroArch's own settings (retroarch.cfg) are not shown.

Each core's options live in config/<core>/<core>.opt of the shared flatpak RetroArch: used by
RetroArch on the PC and by every Wolf session (changes apply to the next sessions).
"""
import json
import os
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from . import ps_config, ra_paths
from .eden_paths import _chown_like

SCHEMA_FILE = Path(__file__).parent / "emulator_settings" / "retroarch.json"
CORES = {"Beetle PSX HW": "PS1 (Beetle PSX HW)", "LRPS2": "PS2 (LRPS2)", "PPSSPP": "PSP (PPSSPP)"}
BACKUP_DIR = Path(ra_paths.RA_DIR) / "wolfy-backups"
TAB_ORDER = ["core_Beetle PSX HW", "core_LRPS2", "ps_RPCS3", "core_PPSSPP", "ps_Vita3K"]  # PS1, PS2, PS3, PSP, Vita


@lru_cache
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text())


def _opt_path(core: str) -> Path:
    return Path(ra_paths.RA_DIR) / "config" / core / f"{core}.opt"


def _read_kv(path: Path) -> dict[str, str]:
    out = {}
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(r'^\s*([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*$', line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def _encode(value) -> str:
    text = str(value)
    if '"' in text or "\n" in text:
        raise HTTPException(400, "Guillemets et retours à la ligne interdits dans une valeur")
    return text


def _mtime() -> float:
    """Latest change of the cores' .opt files and emulators' config.yml (0 if none yet): detects
    concurrent edits."""
    opts = [_opt_path(c).stat().st_mtime for c in CORES if _opt_path(c).is_file()]
    return max([*opts, ps_config.mtime()], default=0.0)


def read() -> dict:
    sch = schema()
    items = []
    for core in CORES:
        core_schema = sch["cores"].get(core, {})
        options = core_schema.get("options", {})
        values = _read_kv(_opt_path(core))
        # every option the core has (default value until RetroArch or Wolfy writes the .opt),
        # then the keys of the file the schema doesn't know (older/newer core version)
        for key in [*options, *(k for k in values if k not in options)]:
            o = options.get(key)
            items.append({
                "section": core, "key": key, "tab": f"core_{core}", "type": "choice" if o else "raw",
                "value": values.get(key, (o or {}).get("default")),
                "label": (o or {}).get("label", key), "help": (o or {}).get("help", ""),
                "default": (o or {}).get("default"),
                "category_label": core_schema.get("categories", {}).get((o or {}).get("category"), "Options")
                if o else "Autres options (inconnues du schéma)",
                "group": None, "min": None, "max": None, "forced": None, "secret": False,
                "options": [{"value": v["value"], "label": v["label"]} for v in o["values"]] if o else None,
            })

    items += ps_config.items()
    return {
        "path": f"{Path(ra_paths.RA_DIR) / 'config'} · {ps_config.PS_DIR}",
        "description": "Options des cœurs PlayStation (PS1, PS2, PSP : partagées avec RetroArch sur le PC) et "
                       "réglages de RPCS3 (PS3) et Vita3K (PS Vita). Les changements s'appliquent aux "
                       "prochaines sessions.",
        "mtime": _mtime(),
        "version": "les sources des cœurs et des émulateurs",
        "tabs": sorted([{"id": f"core_{c}", "label": title} for c, title in CORES.items()] + ps_config.tabs(),
                       key=lambda t: TAB_ORDER.index(t["id"])),
        "items": items,
        "backups": list_backups(),
        "host_running": ra_paths.host_retroarch_running(),
    }


def write(changes: list[dict], mtime: float | None) -> int:
    if mtime is not None and abs(_mtime() - mtime) > 1e-6:
        raise HTTPException(409, "Les options des cœurs ont été modifiées entre-temps : recharge la page.")
    sch = schema()
    core_changes: dict[str, dict[str, str]] = {}
    emulator_changes: dict[str, list[dict]] = {}
    for ch in changes:
        section, key = ch["section"], ch["key"]
        if section in ps_config.EMULATORS:
            emulator_changes.setdefault(section, []).append(ch)
            continue
        if section not in CORES:
            raise HTTPException(400, f"Section inconnue : {section}")
        o = sch["cores"].get(section, {}).get("options", {}).get(key)
        if ch.get("reset") and not o:
            raise HTTPException(400, f"Pas de valeur par défaut connue pour {key}")
        value = o["default"] if ch.get("reset") else ch.get("raw", ch.get("value"))
        if o and o["values"] and value not in [v["value"] for v in o["values"]]:
            raise HTTPException(400, f"Valeur invalide pour {key} : {value}")
        core_changes.setdefault(section, {})[key] = _encode(value)

    if core_changes and ra_paths.host_retroarch_running():
        raise HTTPException(409, "RetroArch est ouvert sur le PC : ferme-le d'abord.")
    for core, kv in core_changes.items():
        _write_opt(core, kv)
    for section, chs in emulator_changes.items():
        ps_config.write(section, chs)
    return len(changes)


def _write_opt(core: str, kv: dict[str, str]) -> None:
    path = _opt_path(core)
    config_dir = path.parent.parent
    if path.is_file():
        lines = path.read_text(errors="replace").split("\n")
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(path, BACKUP_DIR / f"{core}.opt.{datetime.now():%Y-%m-%d_%H-%M-%S}")
        _chown_like(BACKUP_DIR, Path(ra_paths.RA_DIR))
    else:  # core never started on the PC: RetroArch fills in the other options itself
        path.parent.mkdir(parents=True, exist_ok=True)
        _chown_like(path.parent, config_dir if config_dir.is_dir() else Path(ra_paths.RA_DIR))
        lines = [""]
    todo = dict(kv)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in todo:
            lines[i] = f'{m.group(1)} = "{todo.pop(m.group(1))}"'
    lines[-1:-1] = [f'{k} = "{v}"' for k, v in todo.items()]
    tmp = path.with_suffix(".wolfy-tmp")
    tmp.write_text("\n".join(lines))
    _chown_like(tmp, path if path.is_file() else path.parent)
    tmp.replace(path)


def list_backups() -> list[dict]:
    opts = [{"name": p.name, "mtime": p.stat().st_mtime} for p in BACKUP_DIR.glob("*.opt.*")
            if p.name.split(".opt.")[0] in CORES] if BACKUP_DIR.exists() else []
    return sorted(opts + ps_config.list_backups(), key=lambda b: b["mtime"], reverse=True)


def restore(name: str) -> None:
    if ps_config.restore(name):
        return
    src = BACKUP_DIR / name
    if "/" in name or not src.is_file():
        raise HTTPException(404, "Sauvegarde introuvable")
    core = name.split(".opt.")[0]
    if core not in CORES:
        raise HTTPException(400, "Sauvegarde inconnue")
    if ra_paths.host_retroarch_running():
        raise HTTPException(409, "RetroArch est ouvert sur le PC : ferme-le d'abord.")
    dest = _opt_path(core)
    if dest.is_file():
        shutil.copy2(dest, BACKUP_DIR / f"{dest.name}.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    _chown_like(dest, src)
