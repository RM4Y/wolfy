#!/usr/bin/env python3
"""Generate backend/wolfy/emulator_settings/rpcs3.json and vita3k.json from the sources.

RPCS3 (master):
  rpcs3/Emu/system_config.h           every config.yml key (nodes, type, default, min/max)
  rpcs3/Emu/system_config_types.cpp   the names of the enum values (+ cellSysutil.cpp: language, region)
  rpcs3/rpcs3qt/emu_settings_type.cpp, settings_dialog.cpp, tooltips.h   help texts of the settings
Vita3K (master):
  vita3k/config/include/config/config.h   every config.yml key (CONFIG_LIST), type, default
  labels and choices: VITA3K_LABELS below (Vita3K has no machine-readable descriptions)

    python3 tools/gen_ps_schema.py
"""
import json
import re
import urllib.request
from pathlib import Path

RPCS3 = "https://raw.githubusercontent.com/RPCS3/rpcs3/master/rpcs3"
VITA3K = "https://raw.githubusercontent.com/Vita3K/Vita3K/master/vita3k"
OUT = Path(__file__).resolve().parent.parent / "backend/wolfy/emulator_settings"

# symbols of a Linux x86-64 build
DEFINED = {"HAVE_VULKAN", "HAVE_SDL3", "HAVE_LIBEVDEV", "HAVE_FAUDIO", "LLVM_AVAILABLE", "ARCH_X64", "__linux__"}


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def preprocess(src: str) -> str:
    def true(cond: str) -> bool:
        cond = re.sub(r"defined\s*\(?\s*(\w+)\s*\)?", lambda m: str(m.group(1) in DEFINED), cond)
        cond = cond.replace("&&", " and ").replace("||", " or ")
        cond = re.sub(r"!(?!=)", " not ", cond)
        cond = re.sub(r"\b(?!True\b|False\b|and\b|or\b|not\b)[A-Za-z_]\w*\b", "False", cond)
        try:
            return bool(eval(cond, {"__builtins__": {}}))
        except Exception:
            return False

    out, stack = [], []  # stack of [active, branch_taken]
    for line in src.splitlines():
        t = line.strip()
        parent = all(a for a, _ in stack)
        if t.startswith("#ifdef"):
            v = t.split()[1] in DEFINED
            stack.append([parent and v, v])
        elif t.startswith("#ifndef"):
            v = t.split()[1] not in DEFINED
            stack.append([parent and v, v])
        elif t.startswith("#if"):
            v = true(t[3:])
            stack.append([parent and v, v])
        elif t.startswith("#elif") and stack:
            v = not stack[-1][1] and true(t[5:])
            stack[-1] = [all(a for a, _ in stack[:-1]) and v, stack[-1][1] or v]
        elif t.startswith("#else") and stack:
            stack[-1] = [all(a for a, _ in stack[:-1]) and not stack[-1][1], True]
        elif t.startswith("#endif") and stack:
            stack.pop()
        elif parent:
            out.append(line)
    return "\n".join(out)


def number(expr: str):
    """Integer/float literal or constant arithmetic (0xFF, 100'000, (1 << 6) - 1, 1.0f)."""
    expr = re.sub(r"/\*.*?\*/", "", expr).replace("'", "").strip()
    expr = re.sub(r"(?<=[0-9.])[fF]\b|(?<=[0-9])[uUlL]+\b", "", expr)
    if expr in ("true", "false"):
        return int(expr == "true")
    if not re.fullmatch(r"[0-9a-fA-FxX.+\-*/<>()| ]+", expr):
        return None
    try:
        return eval(expr, {"__builtins__": {}})
    except Exception:
        return None


# ------------------------------------------------------------------ RPCS3

def rpcs3_enums() -> dict[str, list[tuple[str, str]]]:
    """enum type -> [(C++ value, name in config.yml)]."""
    enums = {}
    for f in ("Emu/system_config_types.cpp", "Emu/Cell/Modules/cellSysutil.cpp", "Emu/Cell/Modules/cellKb.cpp"):
        try:
            src = preprocess(fetch(f"{RPCS3}/{f}"))
        except Exception:
            continue
        for m in re.finditer(r"fmt_class_string<(\w+)>::format\(.*?\n\}", src, re.S):
            cases = re.findall(r"case\s+([\w:]+)\s*:\s*return\s*\"([^\"]*)\"", m.group(0))
            if cases:
                enums[m.group(1)] = cases
    return enums


def rpcs3_help() -> dict[str, str]:
    """C++ member path in the config (video.write_color_buffers) -> tooltip text."""
    tooltips = {}
    for m in re.finditer(r"const QString (\w+)\s*=\s*tr\(((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\)", fetch(f"{RPCS3}/rpcs3qt/tooltips.h")):
        text = "".join(re.findall(r"\"((?:[^\"\\]|\\.)*)\"", m.group(2)))
        tooltips[m.group(1)] = text.replace("\\n", "\n").replace('\\"', '"')
    location = dict(re.findall(r"emu_settings_type::(\w+),\s*get_cfg_location\(local_cfg\.([\w.]+)\)",
                               fetch(f"{RPCS3}/rpcs3qt/emu_settings_type.cpp")))
    dialog = fetch(f"{RPCS3}/rpcs3qt/settings_dialog.cpp")
    widget_tip = dict(re.findall(r"SubscribeTooltip\(\s*ui->(\w+)\s*,\s*tooltips\.settings\.(\w+)\s*\)", dialog))
    out = {}
    for m in re.finditer(r"Enhance\w*\(\s*emu_settings_type::(\w+)\s*,\s*ui->(\w+)(?:\s*,\s*tooltips\.settings\.(\w+))?", dialog):
        kind, widget, tip = m.groups()
        tip = tip or widget_tip.get(widget)
        if kind in location and tip in tooltips:
            out.setdefault(location[kind], tooltips[tip])
    return out


STRUCT = re.compile(r"\s*struct (\w+)\s*:\s*cfg::node\b")
STRUCT_END = re.compile(r"\s*\}\s*(\w+)\s*\{\s*this\s*\}\s*;")
MEMBER = re.compile(r"\s*((?:cfg::)?\w+(?:<[^>]*>)?)\s+(\w+)\s*\{\s*this\s*,\s*\"([^\"]+)\"\s*(?:,\s*(.*?))?\s*\}\s*;")


def walk(src: str):
    """(struct types from the root, yaml node names, member line match) of each setting, plus
    struct type -> member name (node_vk -> vk)."""
    members, stack, depth = {}, [], 0  # stack: [type, yaml name, depth at open]
    found = []
    for line in src.splitlines():
        m = STRUCT.match(line)
        if m:
            stack.append([m.group(1), None, depth])
        m = re.search(r"cfg::node\(_this,\s*\"([^\"]+)\"\)", line)
        if m and stack and stack[-1][1] is None:
            stack[-1][1] = m.group(1)
        m = STRUCT_END.match(line)
        if m and stack and depth - 1 == stack[-1][2]:
            members[stack.pop()[0]] = m.group(1)
        m = MEMBER.match(line)
        if m and len(stack) > 1 and all(n[1] for n in stack[1:]):  # stack[0] = cfg_root
            found.append(([n[0] for n in stack[1:]], [n[1] for n in stack[1:]], m))
        depth += line.count("{") - line.count("}")
    return found, members


def rpcs3_schema() -> dict:
    src = preprocess(re.sub(r"//[^\n]*", "", fetch(f"{RPCS3}/Emu/system_config.h")))
    enums = rpcs3_enums()
    helps = rpcs3_help()
    # custom setting classes deriving from an enum setting (fifo_setting : cfg::_enum<rsx_fifo_mode>)
    derived = dict(re.findall(r"struct (\w+)\s*:\s*public cfg::(_enum<\w+>)", src))
    found, members = walk(src)
    settings = {}
    for types, path, m in found:
        ctype, member, key, rest = m.groups()
        ctype = "cfg::" + derived[ctype] if ctype in derived else ctype
        args = [a.strip() for a in re.split(r",(?![^<(]*[>)])", rest)] if rest else []
        default = args[0] if args else None
        if ctype == "cfg::_bool":
            entry = {"type": "bool", "default": default == "true"}
        elif re.match(r"cfg::(_int|uint|_float)<", ctype):
            lo, hi = (number(x) for x in re.match(r"cfg::\w+<\s*(.+?)\s*,\s*(.+?)\s*>", ctype).groups())
            entry = {"type": "float" if ctype.startswith("cfg::_float") else "int",
                     "default": number(default) if default else 0, "min": lo, "max": hi}
        elif ctype in ("cfg::uint64", "cfg::uint32", "cfg::uint16"):
            entry = {"type": "int", "default": number(default) if default else 0}
        elif ctype.startswith("cfg::_enum<"):
            values = enums.get(ctype[len("cfg::_enum<"):-1], [])
            if not values:
                continue
            names = dict(values)
            m_index = re.fullmatch(r"\w+\{(\d+)\}", default or "")  # CellSysutilLang{1}: n-th value
            entry = {"type": "choice", "values": list(dict.fromkeys(v for _, v in values)),
                     "default": values[int(m_index.group(1))][1] if m_index else names.get(default) if default else None}
        elif ctype == "cfg::string":
            entry = {"type": "string", "default": (re.findall(r"\"([^\"]*)\"", default or "") or [""])[0]}
        else:
            continue  # lists, maps, logs
        entry.update(path=path + [key], label=key)
        help_text = helps.get(".".join([members.get(t, t) for t in types] + [member]))
        if help_text:
            entry["help"] = help_text
        settings[" › ".join(path + [key])] = entry
    return {"settings": settings}


# ------------------------------------------------------------------ Vita3K

LANGS = [(0, "Japonais"), (1, "Anglais (US)"), (2, "Français"), (3, "Espagnol"), (4, "Allemand"), (5, "Italien"),
         (6, "Néerlandais"), (7, "Portugais (Portugal)"), (8, "Russe"), (9, "Coréen"), (10, "Chinois traditionnel"),
         (11, "Chinois simplifié"), (12, "Finnois"), (13, "Suédois"), (14, "Danois"), (15, "Norvégien"),
         (16, "Polonais"), (17, "Portugais (Brésil)"), (18, "Anglais (UK)"), (19, "Turc")]
# key -> (French label, category, choices [(value, label)] or None, help)
VITA3K_LABELS = {
    "backend-renderer": ("Moteur de rendu", "Graphismes", [("Vulkan", "Vulkan"), ("OpenGL", "OpenGL")], ""),
    "resolution-multiplier": ("Multiplicateur de résolution", "Graphismes",
                              [(0.5, "×0,5"), (0.75, "×0,75"), (1.0, "×1 (natif, 960×544)"), (1.25, "×1,25"),
                               (1.5, "×1,5"), (1.75, "×1,75"), (2.0, "×2 (1920×1088)"), (2.5, "×2,5"),
                               (3.0, "×3"), (4.0, "×4"), (5.0, "×5"), (6.0, "×6"), (8.0, "×8")], ""),
    "screen-filter": ("Filtre d'écran", "Graphismes", [("Nearest", "Plus proche"), ("Bilinear", "Bilinéaire"),
                      ("Bicubic", "Bicubique"), ("FXAA", "FXAA"), ("FSR", "AMD FSR")], ""),
    "anisotropic-filtering": ("Filtrage anisotrope", "Graphismes", [(1, "×1"), (2, "×2"), (4, "×4"), (8, "×8"), (16, "×16")], ""),
    "v-sync": ("Synchronisation verticale (V-Sync)", "Graphismes", None, ""),
    "high-accuracy": ("Haute précision", "Graphismes", None, "Rendu plus fidèle, plus lent."),
    "disable-surface-sync": ("Désactiver la synchronisation des surfaces", "Graphismes", None,
                             "Plus rapide ; peut causer des défauts graphiques dans certains jeux."),
    "texture-cache": ("Cache de textures", "Graphismes", None, ""),
    "async-pipeline-compilation": ("Compilation asynchrone des pipelines", "Graphismes", None,
                                   "Moins de saccades pendant la compilation des shaders (objets parfois invisibles un instant)."),
    "show-compile-shaders": ("Afficher la compilation des shaders", "Graphismes", None, ""),
    "shader-cache": ("Cache de shaders", "Graphismes", None, ""),
    "spirv-shader": ("Shaders SPIR-V (OpenGL)", "Graphismes", None, ""),
    "memory-mapping": ("Mappage mémoire", "Graphismes", [("disabled", "Désactivé"), ("double-buffer", "Double tampon"),
                       ("external-host", "Mémoire hôte externe"), ("page-table", "Table de pages"),
                       ("native-buffer", "Tampon natif")], ""),
    "fps-hack": ("Hack FPS", "Graphismes", None, "Débloque la cadence de certains jeux limités à 30 i/s."),
    "stretch_the_display_area": ("Étirer la zone d'affichage", "Graphismes", None, ""),
    "fullscreen_hd_res_pixel_perfect": ("Plein écran au pixel près", "Graphismes", None, ""),
    "hashless-texture-cache": ("Cache de textures sans hachage", "Graphismes", None, ""),
    "import-textures": ("Importer des textures (packs HD)", "Graphismes", None, ""),
    "export-textures": ("Exporter les textures", "Graphismes", None, ""),
    "audio-backend": ("Moteur audio", "Audio", [("SDL", "SDL"), ("Cubeb", "Cubeb")], ""),
    "audio-volume": ("Volume", "Audio", None, ""),
    "ngs-enable": ("Activer NGS (audio avancé)", "Audio", None, ""),
    "sys-lang": ("Langue de la console", "Système", LANGS, ""),
    "sys-button": ("Bouton de validation", "Système", [(0, "Rond"), (1, "Croix")], ""),
    "sys-date-format": ("Format de date", "Système", [(0, "AAAA/MM/JJ"), (1, "JJ/MM/AAAA"), (2, "MM/JJ/AAAA")], ""),
    "sys-time-format": ("Format d'heure", "Système", [(0, "12 heures"), (1, "24 heures")], ""),
    "pstv-mode": ("Mode PlayStation TV", "Système", None, ""),
    "cpu-opt": ("Optimisations CPU", "Système", None, ""),
    "modules-mode": ("Modules du firmware (LLE)", "Système", [(0, "Automatique"), (1, "Automatique + manuel"), (2, "Manuel")], ""),
    "file-loading-delay": ("Délai de chargement des fichiers (ms)", "Système", None, ""),
    "performance-overlay": ("Affichage des performances", "Affichage à l'écran", None, ""),
    "performance-overlay-detail": ("Détail de l'affichage des performances", "Affichage à l'écran",
                                   [(0, "Minimum"), (1, "Bas"), (2, "Moyen"), (3, "Maximum")], ""),
    "performance-overlay-position": ("Position de l'affichage des performances", "Affichage à l'écran",
                                     [(0, "Haut gauche"), (1, "Haut centre"), (2, "Haut droite"), (3, "Bas gauche"),
                                      (4, "Bas centre"), (5, "Bas droite")], ""),
    "show-live-area-screen": ("Afficher l'écran LiveArea", "Interface", None, ""),
    "controller-analog-multiplier": ("Multiplicateur des sticks", "Entrées", None, ""),
    "disable-motion": ("Désactiver les capteurs de mouvement", "Entrées", None, ""),
    "psn-signed-in": ("Connecté au PSN (simulé)", "Réseau", [(0, "Non"), (1, "Oui")], ""),
    "http-enable": ("HTTP activé", "Réseau", None, ""),
    "log-level": ("Niveau de journal", "Journaux", [(0, "Trace"), (1, "Debug"), (2, "Info"), (3, "Avertissement"),
                  (4, "Erreur"), (5, "Critique"), (6, "Désactivé")], ""),
    "archive-log": ("Archiver le journal par jeu", "Journaux", None, ""),
    "screenshot-format": ("Format des captures d'écran", "Interface", [(0, "Aucun"), (1, "JPEG"), (2, "PNG")], ""),
    "validation-layer": ("Couche de validation Vulkan", "Journaux", None, "Débogage uniquement : ralentit."),
}
# set by every session (ps-session-setup.py) or internal: not shown
VITA3K_HIDDEN = {"show-welcome", "check-for-updates", "check-for-updates-mode", "boot-apps-full-screen",
                 "discord-rich-presence", "initial-setup", "pref-path", "user-id", "user-lang", "user-auto-connect",
                 "gdbstub", "wait-for-debugger", "tracy-primitive-impl", "color-surface-debug", "log-uniforms",
                 "log-active-shaders", "current-ime-lang", "apps-list-grid", "show-mode", "demo-mode",
                 "delay-background", "delay-start", "background-alpha", "gpu-idx", "custom-driver-name"}
KINDS = {"bool": "bool", "int": "int", "uint32_t": "int", "uint64_t": "int", "float": "float", "std::string": "string"}


def vita3k_schema() -> dict:
    src = fetch(f"{VITA3K}/config/include/config/config.h")
    settings = {}
    for ctype, key, default in re.findall(r"code\(\s*([\w:]+)\s*,\s*\"([^\"]+)\"\s*,\s*(.*?)\s*,\s*\w+\s*\)", src):
        if ctype not in KINDS or key in VITA3K_HIDDEN or key.startswith("keyboard-"):
            continue
        kind = KINDS[ctype]
        d = re.sub(r"static_cast<int>\((.*)\)|\(int\)\s*", r"\1", re.sub(r"/\*.*?\*/", "", default)).strip()
        if kind == "bool":
            value = {"true": True, "false": False}.get(d, False)
        elif kind == "string":
            value = (re.findall(r"\"([^\"]*)\"", d) or [""])[0]
        else:
            value = number(d)
        label, category, choices, help_text = VITA3K_LABELS.get(key, (key, "Avancé", None, ""))
        if value is None and choices:
            # enum constant (SCE_SYSTEM_PARAM_LANG_ENGLISH_US, MINIMUM, TOP_LEFT, JPEG…)
            value = {"SCE_SYSTEM_PARAM_LANG_ENGLISH_US": 1, "SCE_SYSTEM_PARAM_ENTER_BUTTON_CROSS": 1,
                     "SCE_SYSTEM_PARAM_DATE_FORMAT_MMDDYYYY": 2, "SCE_SYSTEM_PARAM_TIME_FORMAT_12HOUR": 0,
                     "MINIMUM": 0, "TOP_LEFT": 0, "ModulesMode::AUTOMATIC": 0, "JPEG": 1}.get(d)
        entry = {"type": kind, "default": value, "label": label, "category": category, "help": help_text}
        if choices:
            entry["choices"] = [{"value": v, "label": lbl} for v, lbl in choices]
        settings[key] = entry
    return {"settings": settings}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    r = rpcs3_schema()
    (OUT / "rpcs3.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    v = vita3k_schema()
    (OUT / "vita3k.json").write_text(json.dumps(v, ensure_ascii=False, indent=1))
    print(f"RPCS3 : {len(r['settings'])} réglages ({sum(1 for s in r['settings'].values() if s.get('help'))} avec aide), "
          f"Vita3K : {len(v['settings'])} réglages -> {OUT}")
