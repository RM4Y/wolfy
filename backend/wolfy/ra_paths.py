"""PlayStation (RetroArch) paths: BIOS (RetroArch "system" folder), saves, states, ROM folders,
and the BIOS upload.

Default layout, in the Wolfy project (config/ is not versioned):
    config/playstation/bios     system_directory: pcsx2/bios (PS2 BIOS), PS1 BIOS, PPSSPP files
    config/playstation/saves    savefile_directory (memory cards, PSP saves)
    config/playstation/states   savestate_directory

They are set in the shared retroarch.cfg of the host's flatpak RetroArch (which every Wolf
session copies at start) and mounted at the same absolute path in the sessions. Cores, core
options and playlists stay in RetroArch's own folder.
"""
import io
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from . import settings, store
from .eden_paths import _chown_like, _clean, host, update_app_mounts

RA_DIR = settings.RETROARCH_DIR
CFG = Path(RA_DIR) / "retroarch.cfg"
PS_DIR = f"{settings.WOLFY_HOST_DIR}/config/playstation"
DEFAULTS = {
    "bios": f"{PS_DIR}/bios",
    "saves": f"{PS_DIR}/saves",
    "states": f"{PS_DIR}/states",
    "roms": [f"{settings.GAMES_DIR}/ROMS/{s}" for s in ("ps2", "psp", "psx")],
}
CFG_KEYS = {"bios": "system_directory", "saves": "savefile_directory", "states": "savestate_directory"}
GAME_EXT = (".iso", ".bin", ".cue", ".chd", ".cso", ".pbp", ".elf", ".m3u", ".img", ".mdf", ".zso")

PS2_BIOS_SIZE = 4 * 1024 * 1024
PS1_BIOS_SIZE = 512 * 1024
PS2_COMPANIONS = (".nvm", ".mec", ".rom1", ".rom2", ".erom")


# ------------------------------------------------------------------ retroarch.cfg

def _expand(value: str) -> str:
    # "~" is the host user's home for the flatpak RetroArch
    return str(Path(settings.HOST_HOME) / value[2:]) if value.startswith("~/") else value


def read_cfg() -> dict[str, str]:
    out = {}
    for line in CFG.read_text(errors="replace").splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def write_cfg(changes: dict[str, str]) -> bool:
    """Set keys of retroarch.cfg in place (backup first); -> True if the file changed."""
    lines = CFG.read_text(errors="replace").split("\n")
    todo = dict(changes)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in todo:
            lines[i] = f'{m.group(1)} = "{todo.pop(m.group(1))}"'
    lines[-1:-1] = [f'{k} = "{v}"' for k, v in todo.items()]
    text = "\n".join(lines)
    if text == CFG.read_text(errors="replace"):
        return False
    if host_retroarch_running():
        raise HTTPException(409, "RetroArch est ouvert sur le PC : ferme-le d'abord "
                                 "(il réécrit retroarch.cfg en quittant).")
    backup_dir = Path(RA_DIR) / "wolfy-backups"
    backup_dir.mkdir(exist_ok=True)
    shutil.copy2(CFG, backup_dir / f"retroarch.cfg.{datetime.now():%Y-%m-%d_%H-%M-%S}")
    for old in sorted(backup_dir.glob("retroarch.cfg.*"))[:-20]:
        old.unlink()
    _chown_like(backup_dir, Path(RA_DIR))
    tmp = CFG.with_suffix(".wolfy-tmp")
    tmp.write_text(text)
    st = CFG.stat()
    os.chown(tmp, st.st_uid, st.st_gid)
    tmp.replace(CFG)
    return True


def host_retroarch_running() -> bool:
    """The PC's RetroArch is running (Wolf sessions' RetroArch, in containers, don't count)."""
    for pid in (settings.HOST_ROOT / "proc").glob("[0-9]*"):
        try:
            if (pid / "comm").read_text().strip() != "retroarch":
                continue
            cgroup = (pid / "cgroup").read_text()
        except OSError:
            continue
        if "docker" not in cgroup:
            return True
    return False


# ------------------------------------------------------------------ paths

def current() -> dict:
    cfg = read_cfg()
    paths = {k: _expand(cfg.get(key, "")) for k, key in CFG_KEYS.items()}
    paths["roms"] = store.get("emulator_paths").get("retroarch", {}).get("roms", DEFAULTS["roms"])
    return paths


def _count(p: Path, pattern="*") -> int:
    return sum(1 for f in p.rglob(pattern) if f.is_file()) if p.is_dir() else 0


def bios_files(path: str) -> dict:
    root = host(path)
    ps2 = sorted(f.name for f in (root / "pcsx2" / "bios").glob("*")
                 if f.is_file() and f.stat().st_size == PS2_BIOS_SIZE) if (root / "pcsx2" / "bios").is_dir() else []
    ps1 = sorted(f.name for f in root.glob("*") if f.is_file() and f.stat().st_size == PS1_BIOS_SIZE) \
        if root.is_dir() else []
    return {"ps2": ps2, "ps1": ps1, "ppsspp": (root / "PPSSPP").is_dir()}


def status(paths: dict) -> dict:
    out = {}
    b = bios_files(paths["bios"])
    parts = [f"PS2 : {', '.join(b['ps2']) or 'aucun'}", f"PS1 : {', '.join(b['ps1']) or 'aucun (facultatif)'}"]
    out["bios"] = {"exists": host(paths["bios"]).is_dir(), "ok": bool(b["ps2"]),
                   "detail": " · ".join(parts), "files": b}
    for k, label in (("saves", "fichier(s) de sauvegarde"), ("states", "état(s) sauvegardé(s)")):
        p = host(paths[k])
        out[k] = {"exists": p.is_dir(), "ok": p.is_dir(), "detail": f"{_count(p)} {label}"}
    roms = []
    for d in paths["roms"]:
        p = host(d)
        n = sum(1 for f in p.rglob("*") if f.suffix.lower() in GAME_EXT) if p.is_dir() else 0
        roms.append({"path": d, "exists": p.is_dir(), "ok": n > 0, "detail": f"{n} jeu(x)"})
    out["roms"] = roms
    out["host_retroarch_running"] = host_retroarch_running()
    return out


def _session_mounts(paths: dict) -> list[str]:
    mounts = [f"{paths[k]}:{paths[k]}:rw" for k in ("bios", "saves", "states")
              if paths[k] and not paths[k].startswith(RA_DIR + "/")]
    # gamepad combos settings (combos.py), read live by the session watcher
    mounts.append(f"{PS_DIR}/wolfy:/wolfy-config:ro")
    return mounts + [f"{d}:{d}:ro" for d in paths["roms"]]


def apply(paths: dict, restart_wolf) -> dict:
    paths = {
        **{k: _clean(paths.get(k) or DEFAULTS[k]) for k in ("bios", "saves", "states")},
        "roms": list(dict.fromkeys(_clean(d) for d in paths.get("roms", []) if d.strip())),
    }
    for k, label in (("bios", "BIOS"), ("saves", "Sauvegardes"), ("states", "États")):
        if not host(paths[k]).is_dir():
            raise HTTPException(400, f"{label} : dossier introuvable ({paths[k]})")
    for d in paths["roms"]:
        if not host(d).is_dir():
            raise HTTPException(400, f"ROMs : dossier introuvable ({d})")

    before = current()
    cfg_changed = write_cfg({CFG_KEYS[k]: paths[k] for k in CFG_KEYS})
    previous = store.get("emulator_paths").get("retroarch", {})
    old_mounts = set(previous.get("mounts") or _session_mounts(before))
    old_mounts |= {f"{settings.GAMES_DIR}/ROMS:{settings.GAMES_DIR}/ROMS:ro"}  # original PlayStation app mount
    new_mounts = _session_mounts(paths)
    store.put("emulator_paths", "retroarch", {"roms": paths["roms"], "mounts": new_mounts})
    changed = update_app_mounts("retroarch", old_mounts, new_mounts, restart_wolf, "chemins-playstation")
    return {"paths": paths, "apps_updated": changed, "config_changed": cfg_changed}


# ------------------------------------------------------------------ BIOS upload

def upload_bios(files: list[tuple[str, bytes]]) -> dict:
    """PS2 BIOS (4 Mo .bin + .nvm/.mec…), PS1 BIOS (512 Ko .bin), or a .zip of them."""
    items: list[tuple[str, bytes]] = []
    for name, data in files:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                items += [(Path(m).name, z.read(m)) for m in z.namelist() if not m.endswith("/")]
        else:
            items.append((Path(name).name, data))

    ps2, ps1, companions, ignored = [], [], [], []
    for name, data in items:
        low = name.lower()
        if len(data) == PS2_BIOS_SIZE:
            ps2.append((name, data))
        elif len(data) == PS1_BIOS_SIZE:
            ps1.append((name, data))
        elif low.endswith(PS2_COMPANIONS):
            companions.append((name, data))
        else:
            ignored.append(name)
    if not ps2 and not ps1:
        raise HTTPException(400, "Aucun BIOS reconnu : BIOS PS2 = fichier de 4 Mo, BIOS PS1 = 512 Ko")

    root = Path(current()["bios"])
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    installed = []
    for folder, group in ((root / "pcsx2" / "bios", ps2 + (companions if ps2 else [])), (root, ps1)):
        if not group:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in group:
            dest = folder / name
            if dest.exists():
                backup = root / ".backups" / stamp
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup / name)
            dest.write_bytes(data)
            installed.append(name)
    _chown_like(root, root.parent)
    return {"installed": installed, "ignored": ignored}
