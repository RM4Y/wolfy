#!/usr/bin/env python3
"""Session setup for the Wolf "Steam" app (settings written by Wolfy in /wolfy-config/steam.json).

    steam-setup.py prepare     register the library folders in Steam, print the shell exports
                               for the startup options

~/.steam is this session's Steam folder (chosen by startup-app.sh): config/steam/data, or
config/steam/data-N when other Steam sessions are running.
"""
import json
import re
import shlex
import sys
from pathlib import Path

SETTINGS = Path("/wolfy-config/steam.json")
STEAM = Path.home() / ".steam"


# Steam's data folder (login, userdata, libraryfolders.vdf it actually reads): ~/.steam/steam,
# NOT the install root ~/.steam where steam.sh lives (a libraryfolders.vdf there is ignored)
STEAMDIR = STEAM / "steam"

DEFAULT = {"libraries": [], "startup_mode": "bigpicture", "compositor": "sway",
           "mangohud": False, "proton_log": False, "extra_flags": ""}
MODES = {"bigpicture": "-bigpicture", "gamepadui": "-gamepadui", "desktop": ""}


def log(msg):
    print(f"[steam-setup] {msg}", file=sys.stderr, flush=True)


def settings() -> dict:
    try:
        return {**DEFAULT, **json.loads(SETTINGS.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT)


# ------------------------------------------------------------------ libraryfolders.vdf

def vdf_parse(text: str) -> dict:
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack, key, root = [{}], None, None
    root = stack[0]
    for string, brace in tokens:
        if brace == "{":
            new = {}
            stack[-1][key] = new
            stack.append(new)
            key = None
        elif brace == "}":
            stack.pop()
        elif key is None:
            key = string
        else:
            stack[-1][key] = string
            key = None
    return root


def vdf_dump(data: dict, indent=0) -> str:
    out = []
    for k, v in data.items():
        if isinstance(v, dict):
            out += ["\t" * indent + f'"{k}"', "\t" * indent + "{", vdf_dump(v, indent + 1), "\t" * indent + "}"]
        else:
            out.append("\t" * indent + f'"{k}"\t\t"{v}"')
    return "\n".join(x for x in out if x != "")


def library_meta(path: str) -> dict:
    """label / contentid a library keeps in its own libraryfolder.vdf (Steam matches on them)."""
    try:
        meta = vdf_parse(Path(path, "libraryfolder.vdf").read_text()).get("libraryfolder", {})
    except OSError:
        meta = {}
    return {"label": meta.get("label", ""), "contentid": meta.get("contentid", "0")}


def register_libraries(paths: list[str]) -> None:
    """Add the library folders to Steam's libraryfolders.vdf (Steam fills in the rest)."""
    if not paths:
        return
    for vdf in (STEAMDIR / "steamapps" / "libraryfolders.vdf", STEAMDIR / "config" / "libraryfolders.vdf"):
        vdf.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = vdf_parse(vdf.read_text())
        except OSError:
            data = {}
        folders = data.setdefault("libraryfolders", {})
        if not folders:
            folders["0"] = {"path": str(STEAMDIR), "label": "", "contentid": "0", "totalsize": "0",
                            "update_clean_bytes_tally": "0", "time_last_update_verified": "0", "apps": {}}
        # a ".../steamapps" entry is never a library (it's the folder inside one): drop it
        for k in [k for k, f in folders.items() if k != "0" and isinstance(f, dict)
                  and str(f.get("path", "")).rstrip("/").endswith("/steamapps")]:
            log(f"invalid library removed: {folders.pop(k)['path']}")
        known = {f.get("path") for f in folders.values() if isinstance(f, dict)}
        for path in paths:
            if path in known or not Path(path, "steamapps").is_dir():
                continue
            n = str(max((int(k) for k in folders if k.isdigit()), default=-1) + 1)
            folders[n] = {"path": path, **library_meta(path), "totalsize": "0",
                          "update_clean_bytes_tally": "0", "time_last_update_verified": "0", "apps": {}}
            log(f"library registered: {path}")
        vdf.write_text(vdf_dump(data) + "\n")


def prepare() -> int:
    s = settings()
    try:
        register_libraries(s["libraries"])
    except Exception as exc:  # never block Steam over this
        log(f"libraries not registered: {exc}")
    flags = " ".join(x for x in (MODES.get(s["startup_mode"], "-bigpicture"), s["extra_flags"].strip()) if x)
    exports = {"STEAM_STARTUP_FLAGS": flags, "MANGOHUD": "1" if s["mangohud"] else "0"}
    if s["proton_log"]:
        exports["PROTON_LOG"] = "1"
    lines = [f"export {k}={shlex.quote(v)}" for k, v in exports.items()]
    if not s["proton_log"]:
        lines.append("unset PROTON_LOG")
    # always Sway: under Wolf, Gamescope starts its headless backend (black stream)
    lines += ["unset RUN_GAMESCOPE", "export RUN_SWAY=1"]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["prepare"]:
        sys.exit(prepare())
    else:
        sys.exit(__doc__)
