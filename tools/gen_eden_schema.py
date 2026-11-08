#!/usr/bin/env python3
"""Generate backend/wolfy/emulator_settings/eden.json from Eden's sources.

Reads, for a given Eden tag: every setting declared in common/settings.h and
qt_common/config/uisettings.h (type, default, range, category), the enums of
common/settings_enums.h, the labels/tooltips/enum labels of
qt_common/config/shared_translation.cpp and their official French translation
(dist/languages/fr.ts).

    python3 tools/gen_eden_schema.py v0.2.1
    python3 tools/gen_eden_schema.py eglantine v0.1.0-rc3  # Eglantine (app Switch), a GitHub tag/branch
    (WOLFY_SCHEMA_OUT=<file> writes elsewhere, to compare with the current schema)
"""
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parent.parent / "backend/wolfy/emulator_settings"
if len(sys.argv) > 1 and sys.argv[1] == "eglantine":
    # Eden fork (Switch 2): same files, on GitHub
    TAG = sys.argv[2] if len(sys.argv) > 2 else "nx2"
    BASE = f"https://raw.githubusercontent.com/Eglantine-Community/Eglantine/{TAG}"
    OUT = SCHEMAS / "eglantine.json"
else:
    TAG = sys.argv[1] if len(sys.argv) > 1 else "v0.2.1"
    BASE = f"https://git.eden-emu.dev/eden-emu/eden/raw/tag/{TAG}"
    OUT = SCHEMAS / "eden.json"
if os.environ.get("WOLFY_SCHEMA_OUT"):
    OUT = Path(os.environ["WOLFY_SCHEMA_OUT"])


def fetch(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=60) as r:
        return r.read().decode()


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return preprocess(re.sub(r"//[^\n]*", "", src))


# macros defined for the build Wolfy runs (Linux x86-64 desktop, clang); any other is undefined
# (HAS_NCE: arm64 only, __sun__, __ANDROID__, _WIN32...)
DEFINED = {"__linux__", "__linux", "linux", "__unix__", "__unix", "__x86_64__", "__x86_64", "__amd64__",
           "ARCHITECTURE_x86_64", "__GNUC__", "__clang__", "__ELF__"}


def _is_true(cond: str) -> bool:
    """An #ifdef / #ifndef / #if condition as the preprocessor of that build evaluates it."""
    cond = cond.strip()
    if cond.startswith("#ifdef"):
        return cond.split()[1] in DEFINED
    if cond.startswith("#ifndef"):
        return cond.split()[1] not in DEFINED
    expr = cond.split(None, 1)[1] if " " in cond else "0"
    expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)",
                  lambda m: "1" if (m[1] or m[2]) in DEFINED else "0", expr)
    expr = re.sub(r"__has_\w+\s*\([^)]*\)", "0", expr)
    expr = re.sub(r"\b[A-Za-z_]\w*\b", "0", expr)  # an undefined macro is 0
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    try:
        return bool(eval(expr, {"__builtins__": {}}))  # only digits, operators, and/or/not left
    except Exception:
        raise SystemExit(f"condition non comprise : {cond}")


def preprocess(src: str) -> str:
    """Keep only the branches a Linux desktop build compiles."""
    out, stack = [], []  # stack of [branch_active, any_taken]
    for line in src.splitlines():
        t = line.strip()
        if t.startswith(("#ifdef", "#ifndef", "#if ")):
            parent = all(a for a, _ in stack)
            active = _is_true(t)
            stack.append([parent and active, active])
        elif t.startswith("#elif") and stack:
            active = not stack[-1][1] and _is_true("#if " + t[5:])
            stack[-1] = [all(a for a, _ in stack[:-1]) and active, stack[-1][1] or active]
        elif t.startswith("#else") and stack:
            stack[-1] = [all(a for a, _ in stack[:-1]) and not stack[-1][1], True]
        elif t.startswith("#endif") and stack:
            stack.pop()
        elif all(a for a, _ in stack):
            out.append(line)
    return "\n".join(out)


def split_args(body: str) -> list[str]:
    """Split on top-level commas (ignores commas inside (), {}, <> and strings)."""
    out, depth, cur, in_str = [], 0, "", False
    for i, ch in enumerate(body):
        if ch == '"' and (i == 0 or body[i - 1] != "\\"):
            in_str = not in_str
        if not in_str:
            if ch in "({<":
                depth += 1
            elif ch in ")}>":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def cstr(expr: str) -> str:
    """Concatenated C string literals -> text."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', expr)
    return "".join(parts).encode().decode("unicode_escape").encode("latin-1").decode("utf-8")


# ------------------------------------------------------------------ enums
enums_src = strip_comments(fetch("src/common/settings_enums.h"))
enums: dict[str, list[str]] = {}
for name, members in re.findall(r"ENUM\((\w+),\s*([^;]*?)\)\s*;?\n", enums_src):
    enums[name] = [m.strip() for m in members.split(",") if m.strip()]
for name, members in re.findall(r"enum class (\w+)\s*:\s*\w+\s*\{([^}]*)\}", enums_src):
    enums.setdefault(name, [m.strip() for m in members.split(",") if m.strip()])

# ------------------------------------------------------------------ settings
DECL = re.compile(r"\b(?:SwitchableSetting|Setting)<\s*([\w:]+)[^>]*>\s+(\w+)\s*\{(.*?)\};", re.S)


def parse_settings(src: str, owner: str) -> dict:
    out = {}
    for ctype, ident, body in DECL.findall(strip_comments(src)):
        args = split_args(body)
        # the ini key is the string literal right before Category::X
        cat_idx = next((i for i, a in enumerate(args) if a.startswith("Category::")), None)
        if cat_idx is None or cat_idx < 3 or not re.fullmatch(r'"[^"]*"', args[cat_idx - 1]):
            continue
        name_idx = cat_idx - 1
        cat = next((a.split("::")[1] for a in args[name_idx + 1:] if a.startswith("Category::")), "")
        spec = " ".join(a for a in args[name_idx + 1:] if "Specialization" in a)
        ctype = ctype.replace("Settings::", "").replace("std::", "")
        default = args[1]
        entry = {"id": ident, "owner": owner, "key": args[name_idx].strip('"'),
                 "ctype": ctype, "category": cat}
        if name_idx == 4:
            entry["min"], entry["max"] = args[2], args[3]
        if ctype in enums:
            entry["type"] = "enum"
            entry["enum"] = ctype
            member = default.split("::")[-1]
            entry["default"] = enums[ctype].index(member) if member in enums[ctype] else None
        elif ctype == "bool":
            entry["type"] = "bool"
            entry["default"] = default == "true"
        elif ctype == "string":
            entry["type"] = "string"
            entry["default"] = cstr(default) if '"' in default else ""
        elif ctype in ("float", "double", "f32"):
            entry["type"] = "float"
            entry["default"] = _num(default, float)
        else:
            entry["type"] = "int"
            entry["default"] = _num(default, int)
        for k in ("min", "max"):
            if k in entry:
                entry[k] = _num(entry[k], float if entry["type"] == "float" else int)
        if "Percentage" in spec:
            entry["percent"] = True
        if "Hex" in spec:
            entry["hex"] = True
        if "RuntimeList" in spec:
            entry["runtime_list"] = True
        out[ident] = entry
    return out


def _num(expr: str, kind):
    expr = expr.strip().rstrip("f").replace("'", "")
    try:
        return kind(int(expr, 0)) if kind is int else kind(expr)
    except ValueError:
        m = re.search(r"-?\d+(\.\d+)?", expr)
        return kind(float(m.group())) if m else None


settings = parse_settings(fetch("src/common/settings.h"), "Settings")
settings.update(parse_settings(fetch("src/qt_common/config/uisettings.h"), "UISettings"))

# ------------------------------------------------------------------ labels
tr_src = strip_comments(fetch("src/qt_common/config/shared_translation.cpp"))
labels = {}
for body in re.findall(r"^\s*INSERT\((.*?)\);", tr_src, re.S | re.M):
    args = split_args(body)
    if len(args) < 4:
        continue
    ident = args[1]
    labels[ident] = (cstr(args[2]) if "tr(" in args[2] else "", cstr(args[3]) if "tr(" in args[3] else "")

enum_labels: dict[str, dict[str, str]] = {}
for enum, member, text in re.findall(r"PAIR\((\w+),\s*(\w+),\s*tr\(((?:\s*\"(?:[^\"\\]|\\.)*\"\s*)+)\)\)", tr_src):
    enum_labels.setdefault(enum, {})[member] = cstr(text)

# ------------------------------------------------------------------ French
fr_src = fetch("dist/languages/fr.ts")
french = {}
for msg in re.findall(r"<message>(.*?)</message>", fr_src, re.S):
    src = re.search(r"<source>(.*?)</source>", msg, re.S)
    tr = re.search(r"<translation(?: type=\"(\w+)\")?>(.*?)</translation>", msg, re.S)
    if src and tr and tr.group(2).strip() and tr.group(1) not in ("obsolete", "vanished"):
        french[html.unescape(src.group(1))] = html.unescape(tr.group(2))


# Wolfy's own French for texts the fork has no official translation of yet (fr.ts wins when it has one)
WOLFY_FR = {
    "Volume:": "Volume :", "Slow Speed": "Vitesse lente", "Turbo Speed": "Vitesse turbo",
    "CPU Clocks": "Fréquence du CPU", "GPU Clocks": "Fréquence du GPU", "API:": "API :",
    "RCAS Sharpness:": "Netteté RCAS :",
    "Use NVIDIA DLSS in place of a game's DLSS": "NVIDIA DLSS à la place du DLSS du jeu",
    "Enable post-processing effects": "Effets de post-traitement",
    "Enable Frame Generation": "Génération d'images", "Frame Generation Type": "Type de génération d'images",
    "Frame Generation Multiplier": "Multiplicateur de génération d'images",
    "Target Frame Rate": "Fréquence d'images visée", "Auto Flow Scale": "Échelle du flux optique automatique",
    "Flow Scale": "Échelle du flux optique", "Queue Target": "File d'attente visée",
    "Dump Optical Flow": "Exporter le flux optique", "GPU Fence Behavior": "Comportement des barrières GPU",
    "GPU Fence Behavior:": "Comportement des barrières GPU :",
    "Frame Pacing Mode (Vulkan only)": "Régulation des images (Vulkan uniquement)",
    "Mario Kart World: 30 FPS mode": "Mario Kart World : mode 30 FPS",
    "Mario Kart World: dynamic FPS (experimental)": "Mario Kart World : FPS dynamiques (expérimental)",
    "Enable buffer history": "Historique des tampons", "Fix bloom effects": "Corriger les effets de bloom",
    "GPU Unswizzle Max Texture Size": "Dé-swizzle GPU : taille max. des textures",
    "GPU Unswizzle Stream Size": "Dé-swizzle GPU : taille du flux",
    "GPU Unswizzle Chunk Size": "Dé-swizzle GPU : taille des blocs", "GPU Unswizzle": "Dé-swizzle GPU",
    "Vertex Input Dynamic State": "État dynamique des entrées de sommets",
    "Homebrew Args": "Arguments homebrew",
    "Forces the game to use its native 30 FPS mode at normal game speed. Takes effect after restarting the game.":
        "Force le mode 30 FPS natif du jeu, à vitesse normale. Pris en compte au prochain lancement du jeu.",
    "Lets the game adjust between 30 and 60 FPS using whole-frame timing to maintain normal game speed. "
    "Takes effect after restarting the game and takes precedence over the 30 FPS mode.":
        "Le jeu varie entre 30 et 60 FPS selon le temps de chaque image pour garder sa vitesse normale. "
        "Pris en compte au prochain lancement du jeu ; prioritaire sur le mode 30 FPS.",
}


def fr(text: str) -> str:
    return french.get(text) or WOLFY_FR.get(text, text) if text else ""


# ------------------------------------------------------------------ output
schema = {"eden_tag": TAG, "settings": {}, "enums": {}}
for ident, s in settings.items():
    if s["category"] == "Android":
        continue
    label_en, help_en = labels.get(ident, ("", ""))
    s["label_en"] = label_en.rstrip(":")
    s["label"] = fr(label_en).rstrip(" :")
    s["help"] = fr(help_en)
    s.pop("ctype")
    # same ini key declared twice (e.g. debug_knobs): keep both, keyed by category
    key = s["key"] if s["key"] not in schema["settings"] else f'{s["key"]}@{s["category"]}'
    schema["settings"][key] = s

for name, members in enums.items():
    schema["enums"][name] = [
        {"value": i, "name": m, "label": fr(enum_labels.get(name, {}).get(m, "")) or m}
        for i, m in enumerate(members) if m != "MaxEnum"
    ]

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=1))
print(f"{len(schema['settings'])} réglages, {len(schema['enums'])} énumérations -> {OUT}")
