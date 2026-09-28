#!/usr/bin/env python3
"""Playlists of a PlayStation session, with the cores bundled in the image.

The shared playlists (host RetroArch, mounted) store each game's core as an absolute path to
the PC's cores. The session uses its own copy where those paths point to the image's cores
(/opt/wolfy/cores), and changes made in the session (scans, history, favorites) are written
back to the shared playlists with the PC's core paths.

    playlist-sync.py in      copy shared -> session (at session start)
    playlist-sync.py watch   write session changes back, every few seconds (background)
"""
import os
import sys
import time
from pathlib import Path

RA = Path(os.environ.get("RA_DIR", Path.home() / ".var/app/org.libretro.RetroArch/config/retroarch"))
SHARED = RA / "playlists"
SESSION = Path.home() / ".config/retroarch/playlists"
IMAGE_CORES = "/opt/wolfy/cores/"
# how the PC's RetroArch writes its cores dir in playlists (first one is used when writing back)
PC_CORES = [
    "/home/remy/.var/app/org.libretro.RetroArch/config/retroarch/cores/",
    "~/.var/app/org.libretro.RetroArch/config/retroarch/cores/",
    "/home/retro/.var/app/org.libretro.RetroArch/config/retroarch/cores/",
]


def log(msg):
    print(f"[playlist-sync] {msg}", flush=True)


def to_session(text: str) -> str:
    for prefix in PC_CORES:
        text = text.replace(prefix, IMAGE_CORES)
    return text


def to_shared(text: str) -> str:
    return text.replace(IMAGE_CORES, PC_CORES[0])


def copy_in() -> dict[Path, float]:
    mtimes = {}
    for src in SHARED.rglob("*.lpl"):
        dest = SESSION / src.relative_to(SHARED)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(to_session(src.read_text(errors="replace")))
        mtimes[dest] = dest.stat().st_mtime
    log(f"{len(mtimes)} playlist(s) copied into the session")
    return mtimes


def watch(mtimes: dict[Path, float]) -> None:
    while True:
        time.sleep(3)
        for path in SESSION.rglob("*.lpl"):
            mtime = path.stat().st_mtime
            if mtimes.get(path) == mtime:
                continue
            mtimes[path] = mtime
            dest = SHARED / path.relative_to(SESSION)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".lpl.session-tmp")
                tmp.write_text(to_shared(path.read_text(errors="replace")))
                tmp.replace(dest)
                log(f"saved {dest.relative_to(SHARED)}")
            except OSError as exc:
                log(f"cannot save {dest}: {exc}")


if __name__ == "__main__":
    if sys.argv[1:] == ["in"]:
        copy_in()
    elif sys.argv[1:] == ["watch"]:
        watch({p: p.stat().st_mtime for p in SESSION.rglob("*.lpl")})
    else:
        sys.exit(__doc__)
