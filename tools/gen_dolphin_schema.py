#!/usr/bin/env python3
"""Generate backend/wolfy/emulator_settings/dolphin.json from Dolphin's sources.

Reads, for a given commit of the Better Wii Menu DE fork (the Dolphin of the Wii sessions):
every setting declared in Source/Core/Core/Config/*Settings.cpp (Config::Info: file,
section, key, type, default), the enums they use (headers), and from the Qt settings
windows (Source/Core/DolphinQt) their label, description, choices and bounds, with the
official French translation (Languages/po/fr.po).

    python3 tools/gen_dolphin_schema.py 0e57690c0b0829a2b8870d48e274ead39932e365
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/Gavin-S-Dev/Better-Wii-Menu-DE"
REF = sys.argv[1] if len(sys.argv) > 1 else "0e57690c0b0829a2b8870d48e274ead39932e365"
OUT = Path(__file__).resolve().parent.parent / "backend/wolfy/emulator_settings/dolphin.json"

# Config::System -> file of the user's Config folder (Common/CommonPaths.h); the others
# (SYSCONF in the NAND, pads, per-game and session layers) are not settings files
FILES = {"Main": "Dolphin.ini", "GFX": "GFX.ini", "Logger": "Logger.ini",
         "DualShockUDPClient": "DSUClient.ini", "FreeLook": "FreeLook.ini",
         "Achievements": "RetroAchievements.ini"}
INT_TYPES = {"int", "u32", "s32", "u16", "s16", "u8", "s8", "u64", "s64", "unsigned int", "long"}

# choices built at runtime by Dolphin (backend lists): Linux build
MANUAL_CHOICES = {
    "MAIN_GFX_BACKEND": [("Vulkan", "Vulkan"), ("OGL", "OpenGL"), ("Software Renderer", "Software Renderer"),
                         ("Null", "Null")],
    "MAIN_AUDIO_BACKEND": [("Pulse", "PulseAudio"), ("Cubeb", "Cubeb"), ("OpenAL", "OpenAL"),
                           ("No Audio Output", "No Audio Output")],
    "MAIN_CPU_CORE": [(0, "Interpreter (VERY slow)"), (1, "JIT Recompiler for x86-64 (recommended)"),
                      (5, "Cached Interpreter (slower)")],
    # built in loops in EnhancementsWidget / GeneralWidget
    "GFX_EFB_SCALE": [(0, "Auto (Multiple of 640x528)"), (1, "Native (640x528)"),
                      (2, "2x (1280x1056) – 720p"), (3, "3x (1920x1584) – 1080p"), (4, "4x (2560x2112) – 1440p"),
                      (5, "5x (3200x2640)"), (6, "6x (3840x3168) – 4K"), (7, "7x (4480x3696)"),
                      (8, "8x (5120x4224) – 5K")],
    "GFX_MSAA": [(1, "None"), (2, "2x MSAA"), (4, "4x MSAA"), (8, "8x MSAA")],
    "GFX_SHADER_COMPILATION_MODE": [(0, "Specialized (Default)"), (1, "Exclusive Ubershaders"),
                                    (2, "Hybrid Ubershaders"), (3, "Skip Drawing")],
    "GFX_ENHANCE_MAX_ANISOTROPY": [(-1, "Default"), (0, "1x Anisotropic"), (1, "2x Anisotropic"),
                                   (2, "4x Anisotropic"), (3, "8x Anisotropic"), (4, "16x Anisotropic")],
}


# defaults computed at runtime or behind a function, and labels only given by a group box
MANUAL_DEFAULTS = {"MAIN_EMULATION_SPEED": 1.0, "MAIN_OVERCLOCK": 1.0, "MAIN_VI_OVERCLOCK": 1.0,
                   "MAIN_SYNC_GPU_OVERCLOCK": 1.0, "MAIN_CPU_CORE": 1, "MAIN_AUDIO_BACKEND": "Cubeb",
                   "MAIN_AUTOUPDATE_UPDATE_TRACK": ""}
MANUAL_LABELS = {"GFX_SHADER_COMPILATION_MODE": "Shader Compilation"}


def run(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def checkout(dest: Path) -> None:
    run("git", "clone", "-q", "--filter=blob:none", "--no-checkout", REPO, str(dest))
    run("git", "sparse-checkout", "set", "--no-cone", "/Source/Core/**/*.h", "/Source/Core/Core/Config/",
        "/Source/Core/DolphinQt/", "/Languages/po/fr.po", cwd=dest)
    run("git", "checkout", "-q", REF, cwd=dest)


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<![:\"])//[^\n]*", "", src)


def c_strings(text: str) -> str:
    """Concatenated C string literals -> text."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
    s = "".join(parts)
    return (s.replace('\\n', "\n").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
            .replace("\\t", "\t"))


# ------------------------------------------------------------------ fr.po

def load_po(path: Path) -> dict[str, str]:
    out, cur, field = {}, {"msgid": "", "msgstr": ""}, None
    def flush():
        if cur["msgid"] and cur["msgstr"]:
            out[cur["msgid"]] = cur["msgstr"]
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid "):
            flush()
            cur, field = {"msgid": "", "msgstr": ""}, "msgid"
            cur["msgid"] = c_strings(line[6:])
        elif line.startswith("msgstr "):
            field = "msgstr"
            cur["msgstr"] = c_strings(line[7:])
        elif line.startswith('"') and field:
            cur[field] += c_strings(line)
        elif not line.strip():
            field = None
    flush()
    return out


# ------------------------------------------------------------------ enums

def load_enums(root: Path) -> dict[str, dict[str, int]]:
    enums: dict[str, dict[str, int]] = {}
    for h in root.glob("Source/Core/**/*.h"):
        src = strip_comments(h.read_text(errors="replace"))
        for m in re.finditer(r"enum\s+(?:class\s+|struct\s+)?(\w+)\s*(?::\s*[\w:]+\s*)?\{([^}]*)\}", src):
            name, body = m.group(1), m.group(2)
            values, n = {}, 0
            for item in body.split(","):
                item = item.strip()
                if not item:
                    continue
                mm = re.match(r"(\w+)\s*(?:=\s*(.+))?$", item, re.S)
                if not mm:
                    continue
                if mm.group(2):
                    expr = mm.group(2).strip()
                    try:
                        n = int(eval(re.sub(r"(\d)[uUlL]+\b", r"\1", expr), {}, dict(values)))
                    except Exception:
                        continue
                values[mm.group(1)] = n
                n += 1
            if values:
                enums.setdefault(name, values)
    return enums


# ------------------------------------------------------------------ Config::Info

CONSTANTS: dict[str, str] = {}


def load_constants(root: Path) -> None:
    """constexpr NAME = value; (first definition: the x86-64 branch comes first in Dolphin)."""
    for f in list((root / "Source/Core/Core/Config").glob("*.cpp")) + list(root.glob("Source/Core/**/*.h")):
        for m in re.finditer(r"constexpr\s+[\w:]+\s+(\w+)\s*=\s*([^;]+);", strip_comments(f.read_text(errors="replace"))):
            CONSTANTS.setdefault(m.group(1), m.group(2).strip())


def parse_default(expr: str, kind: str, enum_values: dict | None):
    expr = expr.strip()
    for _ in range(3):
        if expr in CONSTANTS:
            expr = CONSTANTS[expr]
    if kind == "bool":
        return {"true": True, "false": False}.get(expr)
    if kind == "string":
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', expr)
        return c_strings(expr) if m else ("" if expr in ("{}", '""') else None)
    if kind == "enum":
        m = re.search(r"(\w+)\s*$", expr)
        if m and enum_values and m.group(1) in enum_values:
            return enum_values[m.group(1)]
        return None
    try:
        v = eval(re.sub(r"(\d)\.?f\b", r"\1.0", re.sub(r"(\d)[uU]\b", r"\1", expr)), {"__builtins__": {}})
        return int(v) if kind == "int" else float(v)
    except Exception:
        return None


def load_infos(root: Path, enums) -> dict[str, dict]:
    infos = {}
    for cpp in sorted((root / "Source/Core/Core/Config").glob("*Settings.cpp")):
        src = strip_comments(cpp.read_text())
        for m in re.finditer(r"const\s+Info<([\w:<> ]+?)>\s+(\w+)\s*\{\s*\{\s*System::(\w+)\s*,\s*"
                             r'"([^"]+)"\s*,\s*"([^"]+)"\s*\}\s*,\s*(.*?)\}\s*;', src, re.S):
            ctype, name, system, section, key, default = m.groups()
            if system not in FILES:
                continue
            ctype = ctype.strip()
            base = ctype.split("::")[-1]
            if ctype == "bool":
                kind, enum = "bool", None
            elif ctype in INT_TYPES:
                kind, enum = "int", None
            elif ctype in ("float", "double"):
                kind, enum = "float", None
            elif ctype == "std::string":
                kind, enum = "string", None
            elif base in enums:
                kind, enum = "enum", base
            else:
                kind, enum = "int", None
            infos[name] = {
                "name": name, "file": FILES[system], "section": section, "key": key, "type": kind,
                "enum": enum, "default": parse_default(default, kind, enums.get(enum)),
                "source": cpp.name,
            }
    return infos


# ------------------------------------------------------------------ Qt settings windows

PANES = {  # DolphinQt file -> (tab, category)
    "GeneralPane.cpp": ("general", "Général"), "InterfacePane.cpp": ("interface", "Interface"),
    "OnScreenDisplayPane.cpp": ("interface", "Affichage à l'écran"), "AudioPane.cpp": ("audio", "Audio"),
    "GameCubePane.cpp": ("gamecube", "GameCube"), "TriforcePane.cpp": ("gamecube", "Triforce"),
    "WiiPane.cpp": ("wii", "Wii"), "AdvancedPane.cpp": ("advanced", "Avancé"),
    "PathPane.cpp": ("paths", "Dossiers"),
    "GeneralWidget.cpp": ("graphics", "Graphismes › Général"),
    "EnhancementsWidget.cpp": ("graphics", "Graphismes › Améliorations"),
    "HacksWidget.cpp": ("graphics", "Graphismes › Hacks"),
    "AdvancedWidget.cpp": ("graphics", "Graphismes › Avancé"),
    "ColorCorrectionConfigWindow.cpp": ("graphics", "Graphismes › Correction des couleurs"),
    "AchievementSettingsWidget.cpp": ("achievements", "RetroAchievements"),
    "FreeLookWidget.cpp": ("freelook", "Vue libre"),
    "DualShockUDPClientWidget.cpp": ("controllers", "Manettes (DSU)"),
    "ControllersPane.cpp": ("controllers", "Manettes"), "ControllersWindow.cpp": ("controllers", "Manettes"),
}


def balanced_call(src: str, start: int) -> str:
    """Text from the opening '(' at start to its matching ')'."""
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
    return src[start + 1:]


def tr_strings(text: str) -> list[str]:
    return [c_strings(m.group(1)) for m in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', text)]


def load_ui(root: Path) -> dict[str, dict]:
    """Config::NAME -> {label, help, options, min, max, pane}."""
    ui: dict[str, dict] = {}
    for cpp in sorted((root / "Source/Core/DolphinQt").rglob("*.cpp")):
        src = strip_comments(cpp.read_text(errors="replace"))
        if "Config::" not in src:
            continue
        consts = {m.group(1): c_strings(m.group(2)) for m in re.finditer(
            r"(?:static\s+)?(?:constexpr\s+)?(?:const\s+)?char\s+(\w+)\[\]\s*=\s*(?:QT_TR_NOOP|QT_TRANSLATE_NOOP)"
            r"\(\s*(?:\"[^\"]*\"\s*,\s*)?((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\)", src)}
        var_info: dict[str, str] = {}
        var_data: dict[str, dict] = {}

        def entry(info):
            return ui.setdefault(info, {"pane": cpp.name})

        for m in re.finditer(r"(?:(\b[\w\->.]+)\s*=\s*)?new\s+(Config\w+|QCheckBox|QRadioButton)\s*(?:<[^>]*>)?\s*\(", src):
            var, cls = m.group(1), m.group(2)
            args = balanced_call(src, m.end() - 1)
            infos = re.findall(r"Config::(\w+)", args)
            strings = tr_strings(args)
            if cls == "ConfigRadioInt" and infos:
                vm = re.search(r"Config::\w+\s*,\s*(?:static_cast<int>\()?([\w:]+)", args)
                e = entry(infos[0])
                if strings and vm:
                    e.setdefault("radio", []).append((vm.group(1), strings[0]))
                continue
            if not infos:
                if var and cls in ("QCheckBox", "QRadioButton") and strings:
                    var_data.setdefault(var, {})["label"] = strings[0]
                continue
            info = infos[0]
            e = entry(info)
            if var:
                var_info[var] = info
            if cls in ("ConfigBool", "ConfigText", "ConfigUserPath") and strings:
                e.setdefault("label", strings[0])
            elif cls in ("ConfigChoice", "ConfigStringChoice", "ConfigComplexChoice") and strings:
                e.setdefault("options_labels", strings)
                sm = re.search(r"\{([^{}]*)\}", args)
                if cls == "ConfigStringChoice" and sm:
                    # pairs {tr("label"), "value"} or plain list of values
                    pairs = re.findall(r'\{\s*tr\(\s*("(?:[^"\\]|\\.)*")\s*\)\s*,\s*("(?:[^"\\]|\\.)*")\s*\}', args)
                    if pairs:
                        e["string_options"] = [(c_strings(v), c_strings(l)) for l, v in pairs]
            elif cls in ("ConfigSlider", "ConfigInteger", "ConfigFloatSlider"):
                nums = re.findall(r"(-?\d+(?:\.\d+)?)f?\s*,", args.split("Config::")[0])
                if len(nums) >= 2:
                    e.setdefault("min", float(nums[0]) if "." in nums[0] else int(nums[0]))
                    e.setdefault("max", float(nums[1]) if "." in nums[1] else int(nums[1]))
            # choice from a QStringList variable declared just before
            if cls in ("ConfigChoice",) and not strings:
                lm = re.match(r"\s*(\w+)\s*,", args)
                if lm:
                    decl = re.search(rf"{lm.group(1)}\s*(?:=|\{{|\()\s*(?:QStringList)?\s*\{{(.*?)\}}\s*[;)]", src, re.S)
                    if decl:
                        e.setdefault("options_labels", tr_strings(decl.group(1)))

        # manual bindings: Config::Set*(Config::X, m_var->...) / m_var->setChecked(Config::Get(Config::X))
        for m in re.finditer(r"Config::Set\w*\(\s*Config::(\w+)\s*,[^;]*?\b(m_\w+)\s*->", src):
            var_info.setdefault(m.group(2), m.group(1))
        for m in re.finditer(r"\b(m_\w+)\s*->\s*set(?:Checked|CurrentIndex|Value|Text)\(\s*[^;]*?Config::Get\(\s*Config::(\w+)", src):
            var_info.setdefault(m.group(1), m.group(2))

        for var, info in var_info.items():
            e = entry(info)
            short = re.escape(var.split("->")[-1])
            if var in var_data and "label" in var_data[var]:
                e.setdefault("label", var_data[var]["label"])
            # description / title / tooltip
            for dm in re.finditer(rf"\b{short}\s*->\s*(SetDescription|SetTitle|setToolTip)\(\s*(.*?)\)\s*;", src, re.S):
                arg = dm.group(2)
                cm = re.match(r"tr\(\s*(\w+)\s*\)", arg.strip())
                text = consts.get(cm.group(1)) if cm else (tr_strings(arg) or [None])[0]
                if not text:
                    continue
                if dm.group(1) == "SetTitle":
                    e["label"] = text
                else:
                    e.setdefault("help", text)
            # layout label: addRow(tr("Label:"), m_var) / addWidget(new QLabel(tr("Label:")), ...) near it
            lm = re.search(rf"addRow\(\s*tr\(\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\)\s*,\s*{short}\b", src)
            if lm:
                e.setdefault("label", c_strings(lm.group(1)))
            else:
                lm = re.search(rf"new\s+(?:QLabel|ClickableQLabel)\(\s*tr\(\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\)\s*\)"
                               rf"[^;]*;\s*(?:[^;]*;\s*){{0,3}}?[^;]*\b{short}\b", src)
                if lm:
                    e.setdefault("label", c_strings(lm.group(1)))
            # combo items added one by one: m_var->addItem(tr("..."))
            items = [c_strings(x) for x in re.findall(rf"\b{short}\s*->\s*addItem\(\s*tr\(\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+)\)", src)]
            if items and "options_labels" not in e:
                e["options_labels"] = items
    return ui


# ------------------------------------------------------------------ assemble

def clean_help(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return "" if re.fullmatch(r"(%\d\s*)*", text) else text


def clean(label: str) -> str:
    return re.sub(r"&(?!&)", "", label or "").replace("&&", "&").strip().rstrip(":").strip()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "dolphin"
        print(f"checkout {REPO} @ {REF}", file=sys.stderr)
        checkout(root)
        po = load_po(root / "Languages/po/fr.po")
        enums = load_enums(root)
        load_constants(root)
        infos = load_infos(root, enums)
        ui = load_ui(root)

    def fr(text: str | None) -> str:
        if not text:
            return ""
        return po.get(text) or po.get(text.rstrip(":")) or text

    settings = []
    for name, s in infos.items():
        u = dict(ui.get(name, {}))
        if name in MANUAL_LABELS:
            u["label"] = MANUAL_LABELS[name]
        if s["default"] is None and name in MANUAL_DEFAULTS:
            s = {**s, "default": MANUAL_DEFAULTS[name]}
        label_en = clean(u.get("label", ""))
        item = {**s, "label_en": label_en, "label": clean(fr(u.get("label", ""))),
                "help": clean_help(fr(u.get("help"))), "pane": u.get("pane"),
                "min": u.get("min"), "max": u.get("max"), "options": None}
        options = None
        if name in MANUAL_CHOICES:
            options = [{"value": v, "label": fr(l)} for v, l in MANUAL_CHOICES[name]]
        elif u.get("string_options"):
            options = [{"value": v, "label": fr(l)} for v, l in u["string_options"]]
        elif u.get("radio"):
            ev = enums.get(s["enum"] or "", {})
            options = []
            for raw, lbl in u["radio"]:
                val = ev.get(raw.split("::")[-1]) if not raw.lstrip("-").isdigit() else int(raw)
                if val is not None:
                    options.append({"value": val, "label": clean(fr(lbl))})
        elif u.get("options_labels") and s["type"] in ("int", "enum"):
            options = [{"value": i, "label": clean(fr(l))} for i, l in enumerate(u["options_labels"])]
        if options:
            item["options"] = options
            if s["type"] == "int":
                item["type"] = "enum"
            elif s["type"] == "string":
                item["type"] = "choice"
        if item["type"] == "enum" and not item.get("options") and s["enum"]:
            item["options"] = [{"value": v, "label": k} for k, v in enums[s["enum"]].items()]
        settings.append(item)

    labelled = sum(1 for s in settings if s["label"])
    OUT.write_text(json.dumps({"dolphin_ref": REF, "settings": settings}, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(settings)} settings ({labelled} with a label from the Qt windows) -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
