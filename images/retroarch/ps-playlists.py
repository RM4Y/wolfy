#!/usr/bin/env python3
"""PS3 / PS Vita playlists of a PlayStation session (RetroArch XMB), rebuilt at each session start.

The games are found on disk, with their title read from PARAM.SFO:
  PS3 (RPCS3)    game folders of the PS3 ROM folders (disc dumps: <game>/PS3_GAME/USRDIR/EBOOT.BIN,
                 or <game>/USRDIR/EBOOT.BIN), and the games installed in RPCS3 (dev_hdd0/game)
  Vita (Vita3K)  the apps installed in Vita3K (ux0/app/<TITLE ID>)
Each entry runs the launcher core of its emulator (launcher-core.c). These playlists only live in
the session (playlist-sync.py doesn't write them back to the PC's RetroArch).

    ps-playlists.py <session playlists dir>
"""
import json
import os
import struct
import sys
from pathlib import Path

HOME = Path.home()
RPCS3_DIR = HOME / ".config/rpcs3"
VITA3K_FS = HOME / ".local/share/Vita3K/fs"
# PS3 ROM folders chosen in Wolfy (Wolfy > PlayStation > BIOS, jeux…)
DIRS_FILE = Path("/wolfy-config/ps-dirs.json")
CORES = "/opt/wolfy/cores"
PLAYLISTS = {
    "Sony - PlayStation 3.lpl": ("wolfy_rpcs3_libretro.so", "Sony - PlayStation 3 (RPCS3)"),
    "Sony - PlayStation Vita.lpl": ("wolfy_vita3k_libretro.so", "Sony - PlayStation Vita (Vita3K)"),
}


def log(msg):
    print(f"[ps-playlists] {msg}", flush=True)


def read_sfo(path: Path) -> dict:
    """Keys of a PARAM.SFO (strings and integers)."""
    try:
        data = path.read_bytes()
    except OSError:
        return {}
    if data[:4] != b"\0PSF" or len(data) < 20:
        return {}
    key_start, data_start, count = struct.unpack_from("<III", data, 8)
    out = {}
    for i in range(count):
        key_off, fmt, length, _, data_off = struct.unpack_from("<HHIII", data, 20 + i * 16)
        end = data.index(b"\0", key_start + key_off)
        key = data[key_start + key_off:end].decode(errors="replace")
        raw = data[data_start + data_off:data_start + data_off + length]
        out[key] = struct.unpack("<I", raw[:4])[0] if fmt == 0x0404 else raw.split(b"\0")[0].decode(errors="replace")
    return out


def label(sfo: dict, fallback: str) -> str:
    return " ".join((sfo.get("TITLE") or fallback).split())


def ps3_games() -> list[tuple[str, str]]:
    games = {}
    try:
        dirs = json.loads(DIRS_FILE.read_text()).get("ps3", [])
    except (OSError, ValueError):
        dirs = []
    for d in dirs:
        root = Path(d)
        if not root.is_dir():
            continue
        for game in sorted(p for p in root.iterdir() if p.is_dir()):
            for base in (game / "PS3_GAME", game):
                eboot = base / "USRDIR" / "EBOOT.BIN"
                if eboot.is_file() and (base / "PARAM.SFO").is_file():
                    sfo = read_sfo(base / "PARAM.SFO")
                    games.setdefault(sfo.get("TITLE_ID") or str(game), (str(eboot), label(sfo, game.name)))
                    break
    hdd = RPCS3_DIR / "dev_hdd0" / "game"
    if hdd.is_dir():
        for game in sorted(p for p in hdd.iterdir() if p.is_dir()):
            sfo = read_sfo(game / "PARAM.SFO")
            eboot = game / "USRDIR" / "EBOOT.BIN"
            # HG = game installed on the HDD (PSN); GD = update/data of a disc game, not bootable
            if sfo.get("CATEGORY") == "HG" and eboot.is_file():
                games.setdefault(sfo.get("TITLE_ID") or game.name, (str(eboot), label(sfo, game.name)))
    return sorted(games.values(), key=lambda g: g[1].lower())


def vita_games() -> list[tuple[str, str]]:
    apps = VITA3K_FS / "ux0" / "app"
    games = []
    if apps.is_dir():
        for app in sorted(p for p in apps.iterdir() if p.is_dir()):
            sfo = read_sfo(app / "sce_sys" / "param.sfo")
            if (app / "eboot.bin").is_file() and str(sfo.get("CATEGORY", "gd")).startswith("gd"):
                games.append((str(app / "eboot.bin"), label(sfo, app.name)))
    return sorted(games, key=lambda g: g[1].lower())


def write(dest: Path, name: str, games: list[tuple[str, str]]) -> None:
    path = dest / name
    if not games:
        path.unlink(missing_ok=True)
        return
    core, core_name = PLAYLISTS[name]
    core_path = f"{CORES}/{core}"
    doc = {
        "version": "1.5", "default_core_path": core_path, "default_core_name": core_name,
        "label_display_mode": 0, "right_thumbnail_mode": 0, "left_thumbnail_mode": 0,
        "thumbnail_match_mode": 0, "sort_mode": 0,
        "items": [{"path": p, "label": lbl, "core_path": core_path, "core_name": core_name,
                   "crc32": "DETECT", "db_name": name} for p, lbl in games],
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    log(f"{name}: {len(games)} jeu(x)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    write(out, "Sony - PlayStation 3.lpl", ps3_games())
    write(out, "Sony - PlayStation Vita.lpl", vita_games())
