"""Eden's qt-config.ini: read every setting, describe it with the schema generated from
Eden's sources (emulator_settings/eden.json), write changes back in place.

Format (QSettings ini): each setting is a pair of lines
    resolution_setup\\default=false
    resolution_setup=6
and Eden ignores the value while `\\default` is true, so a change also sets it to false.
"""
import json
import os
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from . import settings

SCHEMA_FILE = Path(__file__).parent / "emulator_settings" / "eden.json"
BACKUP_KEEP = 20

# Tabs of the settings page: Eden categories grouped as in Eden's own dialog
TABS = [
    ("system", "Système", ["System", "SystemAudio", "Core"]),
    ("graphics", "Graphismes", ["Renderer"]),
    ("graphics_adv", "Graphismes avancés", ["RendererAdvanced", "RendererExtensions"]),
    ("hacks", "Hacks GPU", ["RendererHacks"]),
    ("cpu", "CPU", ["Cpu", "CpuUnsafe", "CpuDebug"]),
    ("audio", "Audio", ["Audio", "UiAudio"]),
    ("controls", "Manettes", ["Controls"]),
    ("network", "Réseau & multijoueur", ["Network", "Services", "Multiplayer", "WebService"]),
    ("applets", "Applets", ["LibraryApplet"]),
    ("storage", "Stockage", ["DataStorage", "Paths"]),
    ("ui", "Interface", ["Ui", "UiGeneral", "UiLayout", "UiGameList", "Screenshots", "Miscellaneous", "Shortcuts"]),
    ("debug", "Débogage", ["Debugging", "DebuggingGraphics", "RendererDebug", "GpuDriver"]),
    ("shortcuts", "Raccourcis", []),
]
CATEGORY_TAB = {cat: tab for tab, _, cats in TABS for cat in cats}
# keys without a schema entry: tab from their ini section
SECTION_TAB = {
    "Core": "system", "System": "system", "Renderer": "graphics_adv", "Cpu": "cpu", "Audio": "audio",
    "Controls": "controls", "Services": "network", "WebService": "network", "LibraryApplet": "applets",
    "Data%20Storage": "storage", "UI": "ui", "Miscellaneous": "ui", "Debugging": "debug",
}
CATEGORY_LABELS = {
    "System": "Système", "SystemAudio": "Son système", "Core": "Cœur", "Renderer": "Rendu",
    "RendererAdvanced": "Avancé", "RendererExtensions": "Extensions Vulkan", "RendererHacks": "Hacks",
    "Cpu": "CPU", "CpuUnsafe": "Optimisations non sûres", "CpuDebug": "Débogage CPU",
    "Audio": "Audio", "UiAudio": "Audio (interface)", "Controls": "Entrées", "Network": "Réseau",
    "Services": "Services", "Multiplayer": "Multijoueur", "WebService": "Service web",
    "LibraryApplet": "Applets système (HLE = simulé, LLE = firmware)", "DataStorage": "Stockage",
    "Paths": "Chemins", "Ui": "Interface", "UiGeneral": "Général", "UiLayout": "Disposition",
    "UiGameList": "Liste des jeux", "Screenshots": "Captures d'écran", "Miscellaneous": "Divers",
    "Debugging": "Débogage", "DebuggingGraphics": "Débogage graphique", "RendererDebug": "Débogage du rendu",
}

# Per-player controller settings (Controls section, not in the generated schema)
CONTROLLER_TYPES = ["Manette Pro", "Deux Joy-Con", "Joy-Con gauche", "Joy-Con droit", "Portable",
                    "Manette GameCube", "Poké Ball Plus", "NES", "SNES", "N64", "Sega Genesis"]
PLAYER_FIELDS = {
    "connected": ("bool", "Connectée", False),
    "type": ("enum", "Type de manette", 0),
    "vibration_enabled": ("bool", "Vibrations", True),
    "vibration_strength": ("int", "Intensité des vibrations (%)", 100),
}

# Overwritten by the Wolf image (startup-app.sh) at every session start
FORCED = {
    ("UI", "Multiplayer\\nickname"): "Pseudo unique par session (Joueur-XXXX)",
    ("UI", "Multiplayer\\ip"): "IP du salon local, via la passerelle du conteneur",
    ("UI", "Multiplayer\\port"): "Port du salon local",
    ("Services", "network_interface"): "Interface réseau du conteneur",
    ("Services", "airplane_mode"): "Toujours désactivé",
    ("Audio", "output_engine"): "SDL2 (sinon le son part dans une autre session)",
    ("Audio", "output_device"): "auto",
}
SECRET_KEYS = {"eden_token"}

# French labels for settings Eden hides from its own dialog (no translation upstream)
EXTRA_LABELS = {
    "controller_navigation": "Navigation des menus à la manette",
    "enable_joycon_driver": "Pilote Joy-Con natif", "enable_procon_driver": "Pilote Manette Pro natif",
    "vibration_enabled": "Vibrations (global)", "enable_accurate_vibrations": "Vibrations précises",
    "motion_enabled": "Détection de mouvement", "udp_input_servers": "Serveurs de mouvement UDP (cemuhook)",
    "enable_udp_controller": "Manette UDP (cemuhook)", "pause_tas_on_load": "Mettre le TAS en pause au chargement",
    "tas_enable": "Activer le TAS", "tas_loop": "Boucler le TAS",
    "tas_show_recording_dialog": "Fenêtre d'enregistrement TAS", "mouse_enabled": "Émuler la souris",
    "mouse_panning_sensitivity": "Panoramique souris — sensibilité",
    "mouse_panning_x_sensitivity": "Panoramique souris — sensibilité X",
    "mouse_panning_y_sensitivity": "Panoramique souris — sensibilité Y",
    "mouse_panning_deadzone_counterweight": "Panoramique souris — compensation zone morte",
    "mouse_panning_decay_strength": "Panoramique souris — force de décroissance",
    "mouse_panning_min_decay": "Panoramique souris — décroissance minimale",
    "emulate_analog_keyboard": "Émuler un stick analogique au clavier", "keyboard_enabled": "Émuler le clavier",
    "debug_pad_enabled": "Manette de débogage", "touch_device": "Écran tactile (réglages)",
    "touch_from_button_map": "Carte tactile par boutons", "enable_ring_controller": "Ring-Con",
    "enable_ir_sensor": "Caméra infrarouge (Joy-Con droit)", "ir_sensor_device": "Périphérique caméra IR",
    "random_amiibo_id": "ID amiibo aléatoire", "touchscreen_enabled": "Écran tactile",
    "touchscreen_angle": "Écran tactile — angle", "touchscreen_diameter_x": "Écran tactile — diamètre X",
    "touchscreen_diameter_y": "Écran tactile — diamètre Y", "ring_controller": "Ring-Con — liaison",
    "use_virtual_sd": "Carte SD virtuelle", "gamecard_inserted": "Cartouche insérée",
    "gamecard_current_game": "Cartouche = jeu en cours", "gamecard_path": "Chemin de la cartouche",
    "ext_content_from_game_dirs": "Charger mises à jour/DLC depuis les dossiers de jeux",
    "nand_directory": "Dossier NAND", "sdmc_directory": "Dossier carte SD", "load_directory": "Dossier mods (load)",
    "dump_directory": "Dossier des dumps", "tas_directory": "Dossier TAS", "save_directory": "Dossier des sauvegardes",
    "use_gdbstub": "Serveur GDB", "gdbstub_port": "Port GDB", "program_args": "Arguments du programme",
    "dump_exefs": "Dumper l'ExeFS", "dump_nso": "Dumper les NSO", "enable_fs_access_log": "Journal des accès fichiers",
    "quest_flag": "Mode kiosque (Quest)", "use_dev_keys": "Clés de développement",
    "use_debug_asserts": "Assertions de débogage", "use_auto_stub": "Auto-stub des services",
    "enable_all_controllers": "Tous les types de manettes", "perform_vulkan_check": "Vérifier Vulkan au démarrage",
    "disable_web_applet": "Désactiver l'applet web", "gpu_logging_enabled": "Journal GPU",
    "gpu_log_level": "Niveau du journal GPU", "gpu_log_vulkan_calls": "Journaliser les appels Vulkan",
    "gpu_log_shader_dumps": "Dumper les shaders", "gpu_log_memory_tracking": "Suivi mémoire GPU",
    "gpu_log_driver_debug": "Débogage du pilote GPU", "gpu_log_ring_buffer_size": "Taille du tampon du journal GPU",
    "disable_macro_jit": "Désactiver le JIT des macros", "disable_macro_hle": "Désactiver le HLE des macros",
    "serial_battery": "Numéro de série batterie", "serial_unit": "Numéro de série console",
    "debug_knobs": "Réglages de débogage (bits)", "record_frame_times": "Enregistrer les temps d'image",
    "web_api_url": "URL du service web (salons publics)", "eden_username": "Nom d'utilisateur web",
    "eden_token": "Jeton web", "log_filter": "Filtre du journal", "flush_line": "Écrire le journal ligne par ligne",
    "censor_username": "Masquer le nom d'utilisateur dans les journaux", "first_launch": "Premier lancement",
    "network_interface": "Interface réseau", "airplane_mode": "Mode avion",
    "use_speed_limit": "Limiter la vitesse", "use_custom_cpu_ticks": "Ticks CPU personnalisés",
    "vtable_bouncing": "VTable bouncing",
    "cpuopt_page_tables": "Tables de pages", "cpuopt_block_linking": "Liaison des blocs",
    "cpuopt_return_stack_buffer": "Tampon de pile de retour", "cpuopt_fast_dispatcher": "Répartiteur rapide",
    "cpuopt_context_elimination": "Élimination de contexte", "cpuopt_const_prop": "Propagation des constantes",
    "cpuopt_misc_ir": "Optimisations IR diverses", "cpuopt_reduce_misalign_checks": "Moins de vérifications d'alignement",
    "cpuopt_fastmem": "Fastmem", "cpuopt_fastmem_exclusives": "Fastmem exclusifs",
    "cpuopt_recompile_exclusives": "Recompiler les exclusifs", "cpuopt_ignore_memory_aborts": "Ignorer les erreurs mémoire",
    "use_asynchronous_gpu_emulation": "Émulation GPU asynchrone",
    "bg_red": "Fond — rouge", "bg_green": "Fond — vert", "bg_blue": "Fond — bleu",
    "debug": "Couche de débogage graphique", "shader_feedback": "Retour des shaders",
    "nsight_aftermath": "Nsight Aftermath", "disable_shader_loop_safety_checks": "Désactiver la sécurité des boucles de shaders",
    "renderdoc_hotkey": "Raccourci RenderDoc", "disable_buffer_reorder": "Désactiver le réordonnancement des buffers",
    "emulate_bgr565": "Émuler BGR565", "optimize_spirv_output": "Optimiser la sortie SPIR-V",
    "provoking_vertex": "Provoking vertex", "descriptor_indexing": "Descriptor indexing",
    "custom_rtc_enabled": "Horloge personnalisée", "custom_rtc_offset": "Décalage de l'horloge (s)",
    "rng_seed_enabled": "Graine aléatoire fixe", "current_user": "Utilisateur actif",
    "singleWindowMode": "Fenêtre unique", "fullscreen": "Plein écran au démarrage",
    "showFilterBar": "Barre de filtre", "showStatusBar": "Barre d'état", "firstStart": "Premier démarrage",
    "enable_discord_presence": "Statut Discord", "showConsole": "Console de journal",
    "calloutFlags": "Messages d'aide vus", "gui_hide_backend_warning": "Masquer l'avertissement de backend",
    "theme": "Thème", "romsPath": "Dernier dossier ouvert", "recentFiles": "Fichiers récents",
    "language": "Langue de l'interface", "screenshot_path": "Dossier des captures",
    "show_add_ons": "Colonne add-ons", "game_icon_size": "Taille des icônes de jeux",
    "folder_icon_size": "Taille des icônes de dossiers", "row_1_text_id": "Ligne 1 du titre",
    "row_2_text_id": "Ligne 2 du titre", "game_list_mode": "Affichage de la liste",
    "show_game_name": "Afficher le nom des jeux", "cache_game_list": "Mettre en cache la liste des jeux",
    "favorites_expanded": "Favoris dépliés", "show_perf_overlay": "Overlay de performances",
    "show_compat": "Colonne compatibilité", "show_size": "Colonne taille", "show_types": "Colonne type",
    "show_play_time": "Colonne temps de jeu", "enable_screenshot_save_as": "Demander où enregistrer les captures",
    "screenshot_height": "Hauteur des captures (0 = native)",
    "nickname": "Pseudo", "filter_text": "Filtre des salons", "filter_games_owned": "Seulement mes jeux",
    "filter_games_hide_empty": "Masquer les salons vides", "filter_games_hide_full": "Masquer les salons pleins",
    "ip": "Connexion directe — IP", "port": "Connexion directe — port", "room_nickname": "Hébergement — pseudo",
    "room_name": "Hébergement — nom du salon", "max_player": "Hébergement — joueurs max",
    "room_port": "Hébergement — port", "host_type": "Hébergement — visibilité", "game_id": "Hébergement — jeu",
    "room_description": "Hébergement — description",
}


def _shortcut(key: str):
    """UI Shortcuts\\Main%20Window\\<Action>\\KeySeq -> ("Action", "clavier"|"manette") or None."""
    m = re.fullmatch(r"Shortcuts\\Main%20Window\\(.+)\\(KeySeq|Controller_KeySeq)", key)
    if not m:
        return None
    return m.group(1).replace("%20", " ").replace("\\", "/"), "manette" if m.group(2).startswith("C") else "clavier"


@lru_cache
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text())


def _path() -> Path:
    return settings.EDEN_CONFIG


# ------------------------------------------------------------------ parsing

def _parse(lines: list[str]):
    """-> {(section, key): {"line": i, "raw": str}}, {(section, key): default-line index}"""
    values, defaults, section = {}, {}, ""
    for i, line in enumerate(lines):
        if line.startswith("[") and line.rstrip().endswith("]"):
            section = line.strip()[1:-1]
            continue
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.endswith("\\default"):
            defaults[(section, key[: -len("\\default")])] = i
        else:
            values[(section, key)] = {"line": i, "raw": raw}
    return values, defaults


def _decode(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    return raw.replace('\\"', '"').replace("\\\\", "\\")


def _encode(value, kind: str, old_raw: str) -> str:
    if kind == "bool":
        return "true" if value in (True, "true", 1, "1") else "false"
    if kind in ("int", "enum"):
        return str(int(value))
    if kind == "float":
        return repr(float(value))
    text = str(value)
    needs_quotes = (old_raw.startswith('"') or any(c in text for c in ',;="')
                    or text != text.strip())
    text = text.replace("\\", "\\\\")
    return f'"{text.replace(chr(34), chr(92) + chr(34))}"' if needs_quotes else text


def _typed(raw: str, kind: str):
    text = _decode(raw)
    try:
        if kind == "bool":
            return text == "true"
        if kind in ("int", "enum"):
            return int(text)
        if kind == "float":
            return float(text)
    except ValueError:
        pass
    return text


def _describe(section: str, key: str) -> dict | None:
    """Schema entry of a (section, key) of the ini file."""
    m = re.fullmatch(r"player_(\d+)_(\w+)", key)
    if section == "Controls" and m and m.group(2) in PLAYER_FIELDS:
        kind, label, default = PLAYER_FIELDS[m.group(2)]
        entry = {"type": kind, "label": f"Joueur {int(m.group(1)) + 1} — {label}", "default": default,
                 "category": "Controls", "group": f"Joueur {int(m.group(1)) + 1}"}
        if m.group(2) == "type":
            entry["options"] = [{"value": i, "label": t} for i, t in enumerate(CONTROLLER_TYPES)]
        if m.group(2) == "vibration_strength":
            entry.update(min=0, max=100)
        return entry
    sch = schema()["settings"]
    name = key.split("\\")[-1]
    entry = sch.get(name) or sch.get(key)
    if entry is None:
        return None
    # same key declared in two categories (debug_knobs…): prefer the one matching the section
    for alt_key, alt in sch.items():
        if alt_key.startswith(name + "@") and alt["category"].lower().startswith(section.lower()[:4]):
            entry = alt
    entry = dict(entry)
    if entry["type"] == "enum":
        entry["options"] = schema()["enums"].get(entry["enum"], [])
    return entry


# ------------------------------------------------------------------ API

def read() -> dict:
    path = _path()
    if not path.is_file():
        raise HTTPException(404, f"Configuration Eden introuvable : {path}")
    lines = path.read_text().split("\n")
    values, defaults = _parse(lines)
    items = []
    for (section, key), v in values.items():
        desc = _describe(section, key)
        kind = desc["type"] if desc else "raw"
        tab = CATEGORY_TAB.get(desc["category"]) if desc else None
        tab = tab or SECTION_TAB.get(section, "raw")
        shortcut = _shortcut(key) if section == "UI" else None
        if shortcut:
            tab = "shortcuts"
        elif section == "UI" and key.startswith("Shortcuts\\"):
            tab = "raw"
        if not desc and (section == "DisabledAddOns" or re.search(r"\\\d+\\|\\size$", key)
                         or re.fullmatch(r"player_\d+_.*|debug_pad_.*", key)):
            tab = "raw"  # arrays and button bindings: raw editor only
        is_default = None
        if (section, key) in defaults:
            is_default = lines[defaults[(section, key)]].split("=", 1)[1].strip() == "true"
        item = {
            "section": section,
            "key": key,
            "tab": tab,
            "type": kind,
            "raw": v["raw"],
            "value": _typed(v["raw"], kind) if kind != "raw" else v["raw"],
            "is_default": is_default,
            "forced": FORCED.get((section, key)),
            "secret": key in SECRET_KEYS,
        }
        name = key.split("\\")[-1]
        item["label"] = (f"{shortcut[0]} ({shortcut[1]})" if shortcut
                         else EXTRA_LABELS.get(name, ""))
        if shortcut:
            item["group"] = shortcut[0]
        if desc:
            item.update({
                "label": desc.get("label") or desc.get("label_en") or item["label"],
                "help": desc.get("help", ""),
                "default": desc.get("default"),
                "category": desc.get("category"),
                "category_label": CATEGORY_LABELS.get(desc.get("category"), desc.get("category")),
                "group": desc.get("group"),
                "options": desc.get("options"),
                "min": desc.get("min"),
                "max": desc.get("max"),
                "percent": desc.get("percent", False),
            })
        items.append(item)
    tabs = [{"id": t, "label": label} for t, label, _ in TABS]
    tabs.append({"id": "raw", "label": "Fichier brut"})
    return {
        "path": str(path),
        "mtime": path.stat().st_mtime,
        "eden_tag": schema().get("eden_tag"),
        "tabs": tabs,
        "items": items,
        "backups": list_backups(),
    }


def write(changes: list[dict], mtime: float | None) -> int:
    """changes: [{section, key, value | raw | reset}] -> number of lines changed."""
    path = _path()
    if mtime is not None and abs(path.stat().st_mtime - mtime) > 1e-6:
        raise HTTPException(409, "Le fichier a été modifié entre-temps (Eden ?) : recharge la page.")
    lines = path.read_text().split("\n")
    values, defaults = _parse(lines)
    inserts = []  # (line index, text) for missing \default lines
    changed = 0
    for ch in changes:
        section, key = ch["section"], ch["key"]
        if (section, key) not in values:
            raise HTTPException(400, f"Réglage inconnu : [{section}] {key}")
        v = values[(section, key)]
        desc = _describe(section, key)
        kind = desc["type"] if desc else "raw"
        if ch.get("reset"):
            if not desc or desc.get("default") is None:
                raise HTTPException(400, f"Pas de valeur par défaut connue pour {key}")
            new_raw, is_default = _encode(desc["default"], kind, v["raw"]), True
        elif "raw" in ch or kind == "raw":
            new_raw = str(ch.get("raw", ch.get("value", "")))
            is_default = False
        else:
            new_raw = _encode(ch["value"], kind, v["raw"])
            is_default = desc is not None and _typed(new_raw, kind) == desc.get("default")
        if "\n" in new_raw:
            raise HTTPException(400, "Valeur sur plusieurs lignes interdite")
        lines[v["line"]] = f"{key}={new_raw}"
        if (section, key) in defaults:
            lines[defaults[(section, key)]] = f"{key}\\default={'true' if is_default else 'false'}"
        elif desc is not None:
            inserts.append((v["line"], f"{key}\\default={'true' if is_default else 'false'}"))
        changed += 1
    for idx, text in sorted(inserts, reverse=True):
        lines.insert(idx, text)
    _backup()
    _atomic_write(path, "\n".join(lines))
    return changed


def _atomic_write(path: Path, text: str) -> None:
    st = path.stat()
    tmp = path.with_suffix(".wolfy-tmp")
    tmp.write_text(text)
    os.chown(tmp, st.st_uid, st.st_gid)  # Wolfy runs as root, the file belongs to the user
    os.chmod(tmp, st.st_mode & 0o777)
    tmp.replace(path)


def _backup_dir() -> Path:
    return _path().parent / "wolfy-backups"


def _backup() -> None:
    d = _backup_dir()
    if not d.exists():
        d.mkdir()
        st = _path().parent.stat()
        os.chown(d, st.st_uid, st.st_gid)
    dest = d / f"qt-config.ini.{datetime.now():%Y-%m-%d_%H-%M-%S}"
    shutil.copy2(_path(), dest)
    st = _path().stat()
    os.chown(dest, st.st_uid, st.st_gid)
    for old in sorted(d.glob("qt-config.ini.*"))[:-BACKUP_KEEP]:
        old.unlink()


def list_backups() -> list[dict]:
    d = _backup_dir()
    if not d.exists():
        return []
    return [{"name": p.name, "mtime": p.stat().st_mtime}
            for p in sorted(d.glob("qt-config.ini.*"), reverse=True)]


def restore(name: str) -> None:
    src = _backup_dir() / name
    if "/" in name or not src.is_file():
        raise HTTPException(404, "Sauvegarde introuvable")
    _backup()
    _atomic_write(_path(), src.read_text())


# ------------------------------------------------------------------ HOME combo
# Read live by home-combo.py in every Switch session (images/eden in /opt/stacks/wolf)
COMBO_DEFAULT = {"enabled": True, "modifier": "start", "button": "a"}
COMBO_MODIFIERS = ("start", "guide")
COMBO_BUTTONS = ("a", "b", "x", "y")


def _combo_path() -> Path:
    return _path().parent / "wolfy-home-combo.json"


def read_combo() -> dict:
    try:
        data = {**COMBO_DEFAULT, **json.loads(_combo_path().read_text())}
    except (OSError, ValueError):
        data = dict(COMBO_DEFAULT)
    return data


def write_combo(enabled: bool, modifier: str, button: str) -> dict:
    if modifier not in COMBO_MODIFIERS or button not in COMBO_BUTTONS:
        raise HTTPException(400, "Combinaison invalide")
    data = {"enabled": enabled, "modifier": modifier, "button": button}
    path = _combo_path()
    tmp = path.with_suffix(".wolfy-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    st = _path().stat()
    os.chown(tmp, st.st_uid, st.st_gid)
    tmp.chmod(0o644)
    tmp.replace(path)
    return data


# ------------------------------------------------------------------ per-title overrides
# Eden's per-game files (custom/<title id>.ini): "key\\use_global=false" + value.
# The Switch HOME menu (qlaunch) is a title too, and renders in 720p even docked.
QLAUNCH = "0100000000001000"


def _title_path(title_id: str) -> Path:
    return _path().parent / "custom" / f"{title_id}.ini"


def read_override(title_id: str, section: str, key: str):
    """Per-title value, or None when the title follows the global setting."""
    path = _title_path(title_id)
    if not path.is_file():
        return None
    cur, use_global, value = "", True, None
    for line in path.read_text().split("\n"):
        if line.startswith("["):
            cur = line.strip()[1:-1]
        elif cur == section and line.startswith(f"{key}\\use_global="):
            use_global = line.split("=", 1)[1].strip() == "true"
        elif cur == section and line.startswith(f"{key}="):
            value = line.split("=", 1)[1]
    return None if use_global or value is None else value


def write_override(title_id: str, section: str, key: str, value: str | None) -> None:
    """Set a per-title value (None = follow the global setting)."""
    path = _title_path(title_id)
    lines = path.read_text().split("\n") if path.is_file() else []
    prefixes = (f"{key}\\use_global=", f"{key}\\default=", f"{key}=")
    out, cur, done = [], "", False
    new = ([f"{key}\\use_global=true"] if value is None else
           [f"{key}\\use_global=false", f"{key}\\default=false", f"{key}={value}"])
    for line in lines:
        if line.startswith("["):
            cur = line.strip()[1:-1]
        if cur == section and line.startswith(prefixes):
            if not done:
                out.extend(new)
                done = True
            continue
        out.append(line)
    if not done:
        if f"[{section}]" in out:
            out.insert(out.index(f"[{section}]") + 1, "\n".join(new))
        else:
            out.extend(["", f"[{section}]", *new, ""])
    if path.is_file():
        d = _backup_dir()
        d.mkdir(exist_ok=True)
        shutil.copy2(path, d / f"{title_id}.ini.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    else:
        path.parent.mkdir(exist_ok=True)
        path.write_text("")
        st = _path().stat()
        os.chown(path, st.st_uid, st.st_gid)
    _atomic_write(path, "\n".join(out))


def read_wolfy() -> dict:
    res = read_override(QLAUNCH, "Renderer", "resolution_setup")
    return {
        "home_combo": read_combo(),
        "menu_resolution": int(res) if res is not None else None,
        "resolution_options": schema()["enums"]["ResolutionSetup"],
        "global_resolution": next((i["value"] for i in read()["items"]
                                   if i["section"] == "Renderer" and i["key"] == "resolution_setup"), None),
    }


def write_menu_resolution(value: int | None) -> None:
    if value is not None and not 0 <= value < len(schema()["enums"]["ResolutionSetup"]):
        raise HTTPException(400, "Résolution invalide")
    write_override(QLAUNCH, "Renderer", "resolution_setup", None if value is None else str(value))
