"""RetroArch settings for the PlayStation sessions: every key of the shared retroarch.cfg and the
core options (LRPS2 = PS2, PPSSPP = PSP), described with the schema generated from the sources
(emulator_settings/retroarch.json, tools/gen_retroarch_schema.py).

Each Wolf session copies retroarch.cfg when it starts: changes apply to the next sessions.
"""
import json
import os
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from . import ra_paths

SCHEMA_FILE = Path(__file__).parent / "emulator_settings" / "retroarch.json"
CORES = {"LRPS2": "Cœur PS2 (LRPS2)", "PPSSPP": "Cœur PSP (PPSSPP)"}

# Settings stored as numbers or names whose choices are only in RetroArch's C code
CHOICES = {
    "menu_driver": [("xmb", "XMB (PS3/PSP)"), ("ozone", "Ozone"), ("rgui", "RGUI"), ("glui", "Material UI")],
    "video_driver": [("vulkan", "Vulkan"), ("glcore", "OpenGL Core"), ("gl", "OpenGL"), ("sdl2", "SDL2")],
    "audio_driver": [("pulse", "PulseAudio"), ("pipewire", "PipeWire"), ("alsa", "ALSA"), ("sdl2", "SDL2"), ("null", "Aucun")],
    "input_joypad_driver": [("udev", "udev"), ("sdl2", "SDL2"), ("linuxraw", "linuxraw")],
    "video_rotation": [(0, "0°"), (1, "90°"), (2, "180°"), (3, "270°")],
    "screen_orientation": [(0, "0°"), (1, "90°"), (2, "180°"), (3, "270°")],
    "input_menu_toggle_gamepad_combo": [
        (0, "Aucune"), (1, "Bas + Y + L1 + R1"), (2, "L3 + R3"), (3, "L1 + R1 + Start + Select"),
        (4, "Start + Select"), (5, "L3 + R1"), (6, "L1 + R1"), (7, "Maintenir Start (2 s)"),
        (8, "Maintenir Select (2 s)"), (9, "Bas + Select"), (10, "L2 + R2")],
    "input_quit_gamepad_combo": [
        (0, "Aucune"), (1, "Bas + Y + L1 + R1"), (2, "L3 + R3"), (3, "L1 + R1 + Start + Select"),
        (4, "Start + Select"), (5, "L3 + R1"), (6, "L1 + R1"), (7, "Maintenir Start (2 s)"),
        (8, "Maintenir Select (2 s)"), (9, "Bas + Select"), (10, "L2 + R2")],
    "xmb_menu_color_theme": [
        (0, "Vert pomme"), (1, "Violet foncé"), (2, "Bleu électrique"), (3, "Doré"), (4, "Rouge héritage"),
        (5, "Bleu nuit"), (6, "Uni"), (7, "Sous-marin"), (8, "Rouge volcanique"), (9, "Lime"),
        (10, "Pikachu jaune"), (11, "Gameboy violet"), (12, "Lune"), (13, "Soleil"), (14, "Ptérodactyle"),
        (15, "Mer"), (16, "Wallpaper")],
}

# Tab of each RetroArch menu group (French group names from the schema); others by key prefix
GROUP_TABS = {
    "Vidéo": "video", "Résolution adaptée aux écrans CRT ": "video", "Limiteur d'images/s": "video",
    "Compteur de temps par images": "video",
    "Audio ": "audio", "Microphone": "audio", "MIDI": "audio", "Sons du menu": "audio",
    "Apparence": "menu", "Interface utilisateur": "menu", "Visibilité": "menu", "Navigateur de fichiers": "menu",
    "Affichage à l'écran": "osd", "Surimpression à l'écran": "osd", "Pistolet en surimpression": "osd",
    "Souris en surimpression": "osd", "Clavier en surimpression": "osd",
    "Sauvegarde": "saves", "Rembobinage": "saves", "Synchronisation avec le Cloud": "saves",
    "Réseau": "network", "RetroSuccès (RetroAchievements)": "network", "Comptes Cheevos": "network",
    "Dossiers": "dirs",
    "Tir turbo": "input",
}
PREFIX_TABS = [
    ("input_", "input"), ("video_", "video"), ("audio_", "audio"), ("microphone_", "audio"),
    ("menu_", "menu"), ("xmb_", "menu"), ("ozone_", "menu"), ("rgui_", "menu"), ("materialui_", "menu"),
    ("content_show_", "menu"), ("notification_", "osd"), ("savestate", "saves"), ("savefile", "saves"),
    ("autosave", "saves"), ("rewind", "saves"), ("netplay_", "network"), ("cheevos_", "network"),
    ("network_", "network"), ("cloud_sync", "saves"),
]
TABS = [("video", "Vidéo"), ("audio", "Audio"), ("input", "Entrées"), ("menu", "Menu & XMB"),
        ("osd", "Affichage à l'écran"), ("saves", "Sauvegardes & états"), ("network", "Réseau & succès"),
        ("dirs", "Dossiers"), ("other", "Autres")]


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


def _typed(raw: str, kind: str):
    try:
        if kind == "bool":
            return raw == "true"
        if kind == "int":
            return int(float(raw))
        if kind == "float":
            return float(raw)
    except ValueError:
        pass
    return raw


def _encode(value, kind: str) -> str:
    if kind == "bool":
        return "true" if value in (True, "true", 1) else "false"
    if kind == "int":
        return str(int(value))
    if kind == "float":
        return f"{float(value):.6f}"
    text = str(value)
    if '"' in text or "\n" in text:
        raise HTTPException(400, "Guillemets et retours à la ligne interdits dans une valeur")
    return text


def _tab(key: str, group_label: str | None) -> str:
    if group_label in GROUP_TABS:
        return GROUP_TABS[group_label]
    if key.endswith("_directory") or key.endswith("_path") and "directory" in key:
        return "dirs"
    for prefix, tab in PREFIX_TABS:
        if key.startswith(prefix):
            return tab
    return "other"


def read() -> dict:
    sch = schema()
    cfg = ra_paths.read_cfg()
    items = []
    for key, raw in cfg.items():
        s = sch["settings"].get(key)
        kind = s["type"] if s else ("bool" if raw in ("true", "false") else "raw")
        group = sch["groups"].get(s.get("group"), s.get("group")) if s else None
        sub = sch["groups"].get(s.get("sub"), s.get("sub")) if s else None
        item = {
            "section": "retroarch.cfg", "key": key, "type": kind,
            "tab": _tab(key, group), "value": _typed(raw, kind),
            "label": (s or {}).get("label", "").strip(),
            "help": (s or {}).get("help", ""),
            "default": (s or {}).get("default"),
            "category_label": group or "Sans catégorie",
            "group": None,
            "min": (s or {}).get("min"), "max": (s or {}).get("max"),
            "options": None, "forced": None, "secret": "password" in key or key.endswith("_token"),
        }
        if key in CHOICES:
            item["options"] = [{"value": v, "label": lbl} for v, lbl in CHOICES[key]]
            item["type"] = "enum" if isinstance(CHOICES[key][0][0], int) else "choice"
        if sub and sub not in ("State", group):
            item["category_label"] = f"{group} › {sub}" if group else sub
        m = re.match(r"input_player(\d+)_", key)
        if m:  # 16 players × every button: one group per player
            item.update(tab="input", category_label=f"Joueur {m.group(1)}", label=item["label"] or key[len(m.group(0)):])
        elif key.startswith("input_") and re.search(r"_(btn|axis|mbtn)$", key) or (key.startswith("input_") and not s):
            item.update(tab="input", category_label="Raccourcis (touches de fonction RetroArch)")
        items.append(item)

    for core, title in CORES.items():
        core_schema = sch["cores"].get(core, {})
        values = _read_kv(_opt_path(core))
        for key, raw in values.items():
            o = core_schema.get("options", {}).get(key)
            item = {
                "section": core, "key": key, "tab": f"core_{core}", "type": "choice" if o else "raw",
                "value": raw, "label": (o or {}).get("label", key), "help": (o or {}).get("help", ""),
                "default": (o or {}).get("default"),
                "category_label": core_schema.get("categories", {}).get((o or {}).get("category"), "Options")
                if o else "Options", "group": None, "min": None, "max": None, "forced": None, "secret": False,
                "options": [{"value": v["value"], "label": v["label"]} for v in o["values"]] if o else None,
            }
            items.append(item)

    tabs = [{"id": t, "label": label} for t, label in TABS]
    tabs += [{"id": f"core_{c}", "label": title} for c, title in CORES.items() if _opt_path(c).is_file()]
    return {
        "path": str(ra_paths.CFG),
        "description": "Configuration RetroArch partagée : utilisée par RetroArch sur le PC et copiée au démarrage "
                       "de chaque session PlayStation. Les changements s'appliquent aux prochaines sessions.",
        "mtime": ra_paths.CFG.stat().st_mtime,
        "version": f"RetroArch {sch.get('retroarch_tag', '')}",
        "tabs": tabs,
        "items": items,
        "backups": list_backups(),
        "host_running": ra_paths.host_retroarch_running(),
    }


def write(changes: list[dict], mtime: float | None) -> int:
    if mtime is not None and abs(ra_paths.CFG.stat().st_mtime - mtime) > 1e-6:
        raise HTTPException(409, "retroarch.cfg a été modifié entre-temps : recharge la page.")
    sch = schema()
    cfg_changes: dict[str, str] = {}
    core_changes: dict[str, dict[str, str]] = {}
    for ch in changes:
        section, key = ch["section"], ch["key"]
        if section == "retroarch.cfg":
            s = sch["settings"].get(key)
            kind = s["type"] if s else "raw"
            if ch.get("reset"):
                if not s or s.get("default") is None:
                    raise HTTPException(400, f"Pas de valeur par défaut connue pour {key}")
                cfg_changes[key] = _encode(s["default"], kind)
            else:
                value = ch.get("raw", ch.get("value"))
                cfg_changes[key] = _encode(value, kind if kind != "raw" else "string")
        elif section in CORES:
            o = sch["cores"].get(section, {}).get("options", {}).get(key)
            value = o["default"] if ch.get("reset") and o else ch.get("raw", ch.get("value"))
            if o and o["values"] and value not in [v["value"] for v in o["values"]]:
                raise HTTPException(400, f"Valeur invalide pour {key} : {value}")
            core_changes.setdefault(section, {})[key] = _encode(value, "string")
        else:
            raise HTTPException(400, f"Section inconnue : {section}")

    if cfg_changes:
        ra_paths.write_cfg(cfg_changes)
    for core, kv in core_changes.items():
        _write_opt(core, kv)
    return len(changes)


def _write_opt(core: str, kv: dict[str, str]) -> None:
    path = _opt_path(core)
    if ra_paths.host_retroarch_running():
        raise HTTPException(409, "RetroArch est ouvert sur le PC : ferme-le d'abord.")
    lines = path.read_text(errors="replace").split("\n")
    todo = dict(kv)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in todo:
            lines[i] = f'{m.group(1)} = "{todo.pop(m.group(1))}"'
    lines[-1:-1] = [f'{k} = "{v}"' for k, v in todo.items()]
    backup_dir = Path(ra_paths.RA_DIR) / "wolfy-backups"
    backup_dir.mkdir(exist_ok=True)
    shutil.copy2(path, backup_dir / f"{core}.opt.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    st = path.stat()
    tmp = path.with_suffix(".wolfy-tmp")
    tmp.write_text("\n".join(lines))
    os.chown(tmp, st.st_uid, st.st_gid)
    tmp.replace(path)


def list_backups() -> list[dict]:
    d = Path(ra_paths.RA_DIR) / "wolfy-backups"
    if not d.exists():
        return []
    return [{"name": p.name, "mtime": p.stat().st_mtime}
            for p in sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)]


def restore(name: str) -> None:
    d = Path(ra_paths.RA_DIR) / "wolfy-backups"
    src = d / name
    if "/" in name or not src.is_file():
        raise HTTPException(404, "Sauvegarde introuvable")
    if ra_paths.host_retroarch_running():
        raise HTTPException(409, "RetroArch est ouvert sur le PC : ferme-le d'abord.")
    if name.startswith("retroarch.cfg."):
        dest = ra_paths.CFG
    else:
        core = name.split(".opt.")[0]
        if core not in CORES:
            raise HTTPException(400, "Sauvegarde inconnue")
        dest = _opt_path(core)
    shutil.copy2(dest, d / f"{dest.name}.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    st = dest.stat()
    shutil.copyfile(src, dest)
    os.chown(dest, st.st_uid, st.st_gid)
