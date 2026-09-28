#!/usr/bin/env python3
"""Generate backend/wolfy/emulator_settings/eden.json from Eden's sources.

Reads, for a given Eden tag: every setting declared in common/settings.h and
qt_common/config/uisettings.h (type, default, range, category), the enums of
common/settings_enums.h, the labels/tooltips/enum labels of
qt_common/config/shared_translation.cpp and their official French translation
(dist/languages/fr.ts).

    python3 tools/gen_eden_schema.py v0.2.1
"""
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

TAG = sys.argv[1] if len(sys.argv) > 1 else "v0.2.1"
BASE = f"https://git.eden-emu.dev/eden-emu/eden/raw/tag/{TAG}"
OUT = Path(__file__).resolve().parent.parent / "backend/wolfy/emulator_settings/eden.json"


def fetch(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=60) as r:
        return r.read().decode()


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return preprocess(re.sub(r"//[^\n]*", "", src))


def _is_true(cond: str) -> bool:
    """#if conditions as seen by a Linux desktop build."""
    neg = cond.startswith("#ifndef") or "!" in cond
    foreign = any(t in cond for t in ("ANDROID", "_WIN32", "__APPLE__", "_MSC_VER", "__FreeBSD__"))
    return foreign if neg else not foreign


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


def fr(text: str) -> str:
    return french.get(text, text) if text else ""


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
