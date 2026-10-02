#!/usr/bin/env python3
"""Generate backend/wolfy/emulator_settings/retroarch.json from the sources.

RetroArch (tag given, default v1.22.2):
  configuration.c   every retroarch.cfg key, its type and default (macro from config.def.h)
  menu_setting.c    the menu entry of each setting: label id, group/sub-group, min/max/step
  intl/msg_hash_fr.h / msg_hash_us.h   labels and help texts (French, else English)
Cores (libretro_core_options.h): Beetle PSX HW (PS1), LRPS2 (PS2) and PPSSPP (PSP) options,
categories, values.

    python3 tools/gen_retroarch_schema.py v1.22.2
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

TAG = sys.argv[1] if len(sys.argv) > 1 else "v1.22.2"
RA = f"https://raw.githubusercontent.com/libretro/RetroArch/{TAG}"
CORES = {
    "Beetle PSX HW": "https://raw.githubusercontent.com/libretro/beetle-psx-libretro/master/libretro_core_options.h",
    "LRPS2": "https://raw.githubusercontent.com/libretro/ps2/libretroization/libretro/libretro_core_options.h",
    "PPSSPP": "https://raw.githubusercontent.com/hrydgard/ppsspp/master/libretro/libretro_core_options.h",
}
OUT = Path(__file__).resolve().parent.parent / "backend/wolfy/emulator_settings/retroarch.json"


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", src)


FOREIGN = ("ANDROID", "_WIN32", "__APPLE__", "_MSC_VER", "IOS", "_XBOX", "__PS3__", "PSP", "VITA",
           "GEKKO", "HW_RVL", "WIIU", "_3DS", "SWITCH", "HAVE_LIBNX", "__WINRT__", "EMSCRIPTEN", "WEBOS",
           "__QNX__", "DINGUX", "ORBIS", "__PSL1GHT__", "XENON", "RARCH_CONSOLE", "RARCH_MOBILE",
           "HAVE_ODROIDGO2", "MIYOO", "RETROFW", "__MACH__", "OSX", "HAVE_COCOA", "WINAPI_FAMILY",
           "HAVE_LAKKA", "HAVE_STEAM", "__HAIKU__", "__MINGW32__", "_WIN64", "__CELLOS_LV2__", "RS90",
           "__FreeBSD__", "__OpenBSD__", "__NetBSD__", "HAVE_ODROIDGO2", "SN_TARGET_PSP2", "__vita__")


def _defined(sym: str) -> bool:
    """Symbols as defined for a Linux desktop build: other platforms no, features yes."""
    return not any(f in sym for f in FOREIGN)


def _is_true(directive: str) -> bool:
    t = directive.strip()
    if t.startswith("#ifdef"):
        return _defined(t.split()[1])
    if t.startswith("#ifndef"):
        sym = t.split()[1]
        return not _defined(sym) or not sym.startswith("HAVE_")  # include guards, config symbols
    expr = re.sub(r"^#\s*(el)?if", "", t)
    expr = re.sub(r"defined\s*\(?\s*(\w+)\s*\)?", lambda m: str(_defined(m.group(1))), expr)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    expr = re.sub(r"\b(?!True\b|False\b|and\b|or\b|not\b)[A-Za-z_]\w*\b", "1", expr)  # unknown macros
    try:
        return bool(eval(expr, {"__builtins__": {}}))
    except Exception:
        return True


def preprocess(src: str) -> str:
    out, stack = [], []
    for line in src.splitlines():
        t = line.strip()
        if t.startswith(("#ifdef", "#ifndef", "#if ", "#if(")):
            active = _is_true(t)
            stack.append([all(a for a, _ in stack) and active, active])
        elif t.startswith("#elif") and stack:
            active = not stack[-1][1] and _is_true(t)
            stack[-1] = [all(a for a, _ in stack[:-1]) and active, stack[-1][1] or active]
        elif t.startswith("#else") and stack:
            stack[-1] = [all(a for a, _ in stack[:-1]) and not stack[-1][1], True]
        elif t.startswith("#endif") and stack:
            stack.pop()
        elif all(a for a, _ in stack):
            out.append(line)
    return "\n".join(out)


def cstr(expr: str) -> str:
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', expr)
    raw = "".join(parts)
    return raw.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")


def split_args(body: str) -> list[str]:
    out, depth, cur, in_str = [], 0, "", False
    for i, ch in enumerate(body):
        if ch == '"' and (i == 0 or body[i - 1] != "\\"):
            in_str = not in_str
        if not in_str:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def calls(src: str, name_re: str):
    """(name, args) of every call NAME(...) with balanced parentheses."""
    for m in re.finditer(rf"\b({name_re})\s*\(", src):
        i, depth, in_str = m.end(), 1, False
        start = i
        while i < len(src) and depth:
            ch = src[i]
            if ch == '"' and src[i - 1] != "\\":
                in_str = not in_str
            elif not in_str:
                depth += ch == "("
                depth -= ch == ")"
            i += 1
        yield m.group(1), split_args(src[start:i - 1]), m.start()


# ------------------------------------------------------------------ defaults (config.def.h)
defs_src = preprocess(strip_comments(fetch(f"{RA}/config.def.h")))
DEFINES = {}
for m in re.finditer(r"^\s*#define\s+(\w+)\s+(.+?)\s*$", defs_src, re.M):
    DEFINES.setdefault(m.group(1), m.group(2))


def value_of(expr: str, kind: str, depth=0):
    expr = expr.strip().strip("()")
    if depth > 8 or expr in ("NULL", ""):
        return None
    if expr in DEFINES:
        return value_of(DEFINES[expr], kind, depth + 1)
    if kind == "bool":
        return {"true": True, "false": False}.get(expr)
    if kind in ("int", "float"):
        try:
            v = float(expr.rstrip("fFuUlL")) if kind == "float" or "." in expr else int(expr.rstrip("uUlL"), 0)
            return v
        except ValueError:
            return None
    if kind == "string" and '"' in expr:
        return cstr(expr)
    return None


# ------------------------------------------------------------------ keys (configuration.c)
conf_src = preprocess(strip_comments(fetch(f"{RA}/configuration.c")))
KINDS = {"BOOL": "bool", "INT": "int", "UINT": "int", "SIZE": "int", "FLOAT": "float",
         "PATH": "string", "ARRAY": "string"}
settings = {}
by_field = {}
for name, args, _ in calls(conf_src, r"SETTING_(?:BOOL|INT|UINT|SIZE|FLOAT|PATH|ARRAY)"):
    if len(args) < 4 or not args[0].startswith('"'):
        continue
    kind = KINDS[name.split("_", 1)[1]]
    key = cstr(args[0])
    field = re.sub(r"[&\s]", "", args[1])  # settings->bools.video_fullscreen
    entry = settings.setdefault(key, {"type": kind, "field": field})
    if "default" not in entry:
        entry["default"] = value_of(args[3], kind)
    by_field.setdefault(field, key)

# ------------------------------------------------------------------ menu entries (menu_setting.c)
menu_src = preprocess(strip_comments(fetch(f"{RA}/menu/menu_setting.c")))
group = sub = None
events = sorted(
    list(calls(menu_src, r"START_GROUP|START_SUB_GROUP|CONFIG_\w+|menu_settings_list_current_add_range")),
    key=lambda e: e[2])
last = None
for name, args, _ in events:
    if name == "START_GROUP":
        g = next((a for a in args if "MENU_ENUM_LABEL_VALUE_" in a or a.startswith('"')), None)
        group = re.search(r"MENU_ENUM_LABEL_VALUE_\w+", g).group(0) if g and "MENU_ENUM" in g else (cstr(g) if g else None)
        sub = None
    elif name == "START_SUB_GROUP":
        g = args[2] if len(args) > 2 else ""
        sub = re.search(r"MENU_ENUM_LABEL_VALUE_\w+", g).group(0) if "MENU_ENUM" in g else cstr(g)
    elif name.startswith("CONFIG_"):
        field = next((re.sub(r"[&\s]", "", a) for a in args if "settings->" in a), None)
        label = next((a for a in args if a.startswith("MENU_ENUM_LABEL_VALUE_")), None)
        last = None
        if field and field in by_field and label:
            key = by_field[field]
            settings[key].setdefault("label_id", label)
            settings[key].setdefault("group", group)
            settings[key].setdefault("sub", sub)
            last = key
    elif name == "menu_settings_list_current_add_range" and last and len(args) >= 5:
        lo, hi, step = (value_of(a, "float") for a in args[2:5])
        if lo is not None and hi is not None and "min" not in settings[last]:
            settings[last].update(min=lo, max=hi, step=step)

# ------------------------------------------------------------------ texts
def msg_hash(url):
    src = fetch(url)
    return {m.group(1): cstr(m.group(2)) for m in re.finditer(
        r"MSG_HASH\(\s*(\w+)\s*,\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\)", src)}


fr = msg_hash(f"{RA}/intl/msg_hash_fr.h")
us = msg_hash(f"{RA}/intl/msg_hash_us.h")


def text(enum):
    if not enum:
        return ""
    return fr.get(enum) or us.get(enum) or ""


schema = {"retroarch_tag": TAG, "settings": {}, "groups": {}, "cores": {}}
for key, s in settings.items():
    label_id = s.pop("label_id", None)
    s.pop("field", None)
    s["label"] = text(label_id)
    s["help"] = text(label_id.replace("LABEL_VALUE_", "SUBLABEL_")) if label_id else ""
    for g in ("group", "sub"):
        if s.get(g) and s[g].startswith("MENU_ENUM_"):
            schema["groups"][s[g]] = text(s[g]) or s[g]
    if s["type"] == "int" and isinstance(s.get("default"), float):
        s["default"] = int(s["default"])
    schema["settings"][key] = s


# ------------------------------------------------------------------ core options
VALUE_FR = {"disabled": "Désactivé", "enabled": "Activé", "auto": "Auto", "Auto": "Auto",
            "off": "Désactivé", "on": "Activé", "none": "Aucun", "None": "Aucun"}
CATEGORY_FR = {"system": "Système", "video": "Vidéo", "audio": "Audio", "input": "Entrées",
               "emulation": "Émulation", "hacks": "Hacks", "network": "Réseau", "hotkey": "Raccourcis",
               "hw_hacks": "Hacks matériels", "gs": "Rendu (GS)", "texture_replacement": "Remplacement de textures",
               "upscaling": "Mise à l'échelle", "performance": "Performances", "cheats": "Codes de triche",
               "osd": "Affichage à l'écran", "memcards": "Memory cards", "pgxp": "PGXP (géométrie précise)"}


def block(src: str, decl: str) -> str:
    i = src.index(decl)
    i = src.index("{", i)
    depth, j = 0, i
    while True:
        depth += src[j] == "{"
        depth -= src[j] == "}"
        j += 1
        if depth == 0:
            return src[i + 1:j - 1]


def entries(body: str) -> list[str]:
    out, depth, cur, in_str = [], 0, "", False
    for i, ch in enumerate(body):
        if ch == '"' and body[i - 1] != "\\":
            in_str = not in_str
        if not in_str:
            if ch == "{":
                depth += 1
                if depth == 1:
                    cur = ""
                    continue
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(cur)
                    continue
        if depth >= 1:
            cur += ch
    return out


def scalars(entry: str):
    """Top-level tokens of an option entry: strings/NULL, and the nested values block."""
    tokens, values = [], None
    for part in split_args(entry):
        if part.startswith("{"):
            values = [split_args(v) for v in entries(part[1:-1])]
        else:
            tokens.append(None if part == "NULL" else cstr(part))
    return tokens, values


# option keys written as a macro in some cores (Beetle PSX HW: BEETLE_OPT(cpu_freq_scale))
KEY_MACROS = {r"BEETLE_OPT\(\s*(\w+)\s*\)": r'"beetle_psx_hw_\1"'}

for core, url in CORES.items():
    src = preprocess(strip_comments(fetch(url)))
    for macro, repl in KEY_MACROS.items():
        src = re.sub(macro, repl, src)
    cats = {}
    if "option_cats_us[]" in src:
        for e in entries(block(src, "option_cats_us[]")):
            t, _ = scalars(e)
            if t and t[0]:
                cats[t[0]] = CATEGORY_FR.get(t[0], t[1] or t[0])
    options = {}
    decl = "option_defs_us[]"
    for e in entries(block(src, decl)):
        t, values = scalars(e)
        if not t or not t[0]:
            continue
        if len(t) >= 7:   # v2: key, desc, desc_categorized, info, info_categorized, category, default
            key, desc, desc_cat, info, _, cat, default = t[:7]
        else:             # v1: key, desc, info, default
            key, desc, info, default = (t + [None] * 4)[:4]
            desc_cat, cat = None, None
        vals = [{"value": cstr(v[0]), "label": VALUE_FR.get(cstr(v[0]), cstr(v[1]) if len(v) > 1 and v[1] != "NULL" else cstr(v[0]))}
                for v in (values or []) if v and v[0] != "NULL"]
        options[key] = {"label": desc_cat or desc or key, "help": info or "", "category": cat,
                        "values": vals, "default": default}
    schema["cores"][core] = {"categories": cats, "options": options}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=1))
labelled = sum(1 for s in schema["settings"].values() if s["label"])
print(f"{len(schema['settings'])} réglages ({labelled} avec libellé), "
      + ", ".join(f"{c}: {len(v['options'])} options" for c, v in schema["cores"].items()) + f" -> {OUT}")
