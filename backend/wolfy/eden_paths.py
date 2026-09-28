"""Switch (Eden) paths: keys, firmware (NAND), ROM folders, users (profiles + saves),
and the keys / firmware uploads.

Default layout, in the Wolfy project (config/ is not versioned):
    config/switch/keys    prod.keys, title.keys
    config/switch/nand    Eden NAND: firmware (system/Contents/registered), installed content
    config/switch/users   Eden save dir: system/save (profiles, system settings) + user/save (games)

They live in two places that must agree:
- Eden's shared qt-config.ini ([Data%20Storage] nand/save dirs, [UI] game dirs), used by the
  host Eden and copied into every Wolf session;
- the mounts of the Wolf apps running Eden (config.toml), so each host path exists at the
  same absolute path in the session container. Keys have no Eden setting (always
  <data dir>/keys): <data dir>/keys is made a symlink to the keys folder, which is mounted
  at the same path in the sessions (the host Eden follows the same link).

Host paths are checked through the read-only host mount (settings.HOST_ROOT).
"""
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from . import eden_config, settings, store, wolf_config

DATA_DIR = settings.EDEN_DATA_DIR                 # host Eden data dir
SESSION_DATA_DIR = "/home/retro/.local/share/eden"  # same dir inside the sessions
SWITCH_DIR = f"{settings.WOLFY_HOST_DIR}/config/switch"
DEFAULTS = {
    "keys": f"{SWITCH_DIR}/keys",
    "firmware": f"{SWITCH_DIR}/nand",
    "roms": ["/mnt/Jeux/ROMS/switch"],
    "users": f"{SWITCH_DIR}/users",
}
GAME_EXT = (".xci", ".nsp", ".nca", ".nro", ".nso", ".xcz", ".nsz")
SPECIAL_GAMEDIRS = ("SDMC", "UserNAND", "SysNAND")


def host(path: str) -> Path:
    return settings.HOST_ROOT / path.lstrip("/")


def _clean(path: str) -> str:
    path = path.strip()
    if path and not path.startswith("/"):
        raise HTTPException(400, f"Chemin absolu attendu : {path}")
    return path.rstrip("/") if path != "/" else path


# ------------------------------------------------------------------ reading

def _ini_lines() -> list[str]:
    return eden_config._path().read_text().split("\n")


def _ini_value(lines, key) -> str:
    for line in lines:
        if line.startswith(f"{key}="):
            return eden_config._decode(line.split("=", 1)[1])
    return ""


def _gamedirs(lines) -> list[str]:
    dirs = {}
    for line in lines:
        m = re.match(r"Paths\\gamedirs\\(\d+)\\path=(.*)$", line)
        if m:
            dirs[int(m.group(1))] = eden_config._decode(m.group(2))
    return [dirs[i] for i in sorted(dirs)]


def current() -> dict:
    lines = _ini_lines()
    keys = Path(DATA_DIR) / "keys"
    return {
        "keys": os.readlink(keys) if keys.is_symlink() else str(keys),
        "firmware": _ini_value(lines, "nand_directory") or DEFAULTS["firmware"],
        "roms": [d for d in _gamedirs(lines) if d not in SPECIAL_GAMEDIRS],
        "users": _ini_value(lines, "save_directory"),
    }


def status(paths: dict) -> dict:
    """What is found at each path (shown next to the fields)."""
    out = {}
    keys = host(paths["keys"])
    found = [k for k in ("prod.keys", "title.keys") if (keys / k).is_file()]
    out["keys"] = {"ok": "prod.keys" in found, "exists": keys.is_dir(),
                   "detail": ", ".join(found) or "aucune clé trouvée"}

    nand = host(paths["firmware"])
    reg = nand / "system" / "Contents" / "registered"
    ncas = len(list(reg.glob("*"))) if reg.is_dir() else 0
    version = _firmware_version()
    out["firmware"] = {"ok": ncas > 0, "exists": nand.is_dir(),
                       "detail": (f"firmware {version} · " if version and ncas else "")
                                 + (f"{ncas} fichiers système" if ncas else "aucun firmware installé")}

    roms = []
    for d in paths["roms"]:
        p = host(d)
        n = sum(1 for f in p.rglob("*") if f.suffix.lower() in GAME_EXT) if p.is_dir() else 0
        roms.append({"path": d, "exists": p.is_dir(), "ok": n > 0, "detail": f"{n} jeu(x)"})
    out["roms"] = roms

    users = host(paths["users"]) if paths["users"] else nand
    game_saves = users / "user" / "save"
    saves = [p for p in game_saves.glob("*/*/*") if p.is_dir()] if game_saves.is_dir() else []
    profiles = (users / "system" / "save" / "8000000000000010").is_dir()
    out["users"] = {"ok": users.is_dir() and profiles, "exists": users.is_dir(),
                    "detail": f"{len(saves)} sauvegarde(s) de jeux · profils {'présents' if profiles else 'absents'}"
                              + ("" if paths["users"] else " · dans la NAND")}
    return out


def _firmware_version() -> str | None:
    log = host(f"{DATA_DIR}/log/eden_log.txt")
    try:
        with open(log, errors="replace") as f:
            head = f.read(20000)
    except OSError:
        return None
    m = re.search(r"Installed firmware: ([\d.]+)", head)
    return m.group(1) if m else None


def browse(path: str) -> dict:
    """Sub-folders of a host folder (folder picker)."""
    path = _clean(path) or "/"
    p = host(path)
    if not p.is_dir():
        raise HTTPException(404, f"Dossier introuvable : {path}")
    dirs = sorted((c.name for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")),
                  key=str.lower)
    return {"path": path, "parent": str(Path(path).parent) if path != "/" else None, "dirs": dirs[:500]}


# ------------------------------------------------------------------ writing

def _session_mounts(paths: dict) -> list[str]:
    """Extra mounts the Eden sessions need for these paths."""
    mounts = []
    # <data dir>/keys links there (see _link_keys)
    if not _in_data_dir(paths["keys"]):
        mounts.append(f"{paths['keys']}:{paths['keys']}:ro")
    for p in (paths["firmware"], paths["users"]):
        if p and not (p == DATA_DIR or p.startswith(DATA_DIR + "/")):
            mounts.append(f"{p}:{p}:rw")
    mounts += [f"{d}:{d}:ro" for d in paths["roms"]]
    return mounts


def _in_data_dir(path: str) -> bool:
    return path == DATA_DIR or path.startswith(DATA_DIR + "/")


def _chown_like(path: Path, ref: Path) -> None:
    st = ref.stat()
    for p in [path, *path.rglob("*")] if path.is_dir() else [path]:
        os.lchown(p, st.st_uid, st.st_gid)


def _link_keys(keys: str) -> None:
    """Make <data dir>/keys point to the keys folder (Eden has no keys path setting)."""
    link = Path(DATA_DIR) / "keys"
    if str(link) == keys or (link.is_symlink() and os.readlink(link) == keys):
        return
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        link.rename(link.with_name(f"keys.bak-{datetime.now():%Y-%m-%d_%H-%M-%S}"))
    link.symlink_to(keys)
    _chown_like(link, link.parent)


def _write_ini(paths: dict) -> bool:
    """-> True when qt-config.ini changed."""
    before = current()
    if (before["firmware"], before["users"], before["roms"]) == (paths["firmware"], paths["users"], paths["roms"]):
        return False
    lines = _ini_lines()
    # data storage
    for key, value in (("nand_directory", paths["firmware"]), ("save_directory", paths["users"])):
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
            elif line.startswith(f"{key}\\default="):
                lines[i] = f"{key}\\default={'true' if key == 'save_directory' and not value else 'false'}"
    if before["roms"] == paths["roms"]:
        eden_config._backup()
        eden_config._atomic_write(eden_config._path(), "\n".join(lines))
        return True
    # game dirs: keep Eden's special entries, replace the folders
    old = {}
    for line in lines:
        m = re.match(r"Paths\\gamedirs\\(\d+)\\(\w+)(\\default)?=(.*)$", line)
        if m and not m.group(3):
            old.setdefault(int(m.group(1)), {})[m.group(2)] = m.group(4)
    special = [e for _, e in sorted(old.items()) if eden_config._decode(e.get("path", "")) in SPECIAL_GAMEDIRS]
    by_path = {eden_config._decode(e.get("path", "")): e for e in old.values()}
    entries = special + [{"path": d, "deep_scan": by_path.get(d, {}).get("deep_scan", "false"),
                          "expanded": by_path.get(d, {}).get("expanded", "true")} for d in paths["roms"]]
    lines = [l for l in lines if not re.match(r"Paths\\gamedirs\\\d+\\", l)]
    try:
        at = next(i for i, l in enumerate(lines) if l.startswith("Paths\\gamedirs\\size="))
    except StopIteration:
        raise HTTPException(500, "Liste des dossiers de jeux absente de qt-config.ini")
    lines[at] = f"Paths\\gamedirs\\size={len(entries)}"
    block = []
    for n, e in enumerate(entries, 1):
        block.append(f"Paths\\gamedirs\\{n}\\path={e['path']}")
        # Eden marks values equal to its defaults (deep_scan off, expanded on)
        for key, default in (("deep_scan", "false"), ("expanded", "true")):
            block += [f"Paths\\gamedirs\\{n}\\{key}\\default={'true' if e[key] == default else 'false'}",
                      f"Paths\\gamedirs\\{n}\\{key}={e[key]}"]
    lines[at + 1:at + 1] = block
    eden_config._backup()
    eden_config._atomic_write(eden_config._path(), "\n".join(lines))
    return True


def apply(paths: dict, restart_wolf) -> dict:
    """Validate, write Eden's config, update the Eden apps' mounts (restarts Wolf if they change)."""
    paths = {
        "keys": _clean(paths.get("keys") or DEFAULTS["keys"]),
        "firmware": _clean(paths.get("firmware") or DEFAULTS["firmware"]),
        "roms": list(dict.fromkeys(_clean(d) for d in paths.get("roms", []) if d.strip())),
        "users": _clean(paths.get("users") or ""),
    }
    for label, p in (("Clés", paths["keys"]), ("Firmware", paths["firmware"]), ("Utilisateurs", paths["users"])):
        if p and not host(p).is_dir():
            raise HTTPException(400, f"{label} : dossier introuvable ({p})")
    for d in paths["roms"]:
        if not host(d).is_dir():
            raise HTTPException(400, f"ROMs : dossier introuvable ({d})")

    ini_changed = _write_ini(paths)
    _link_keys(paths["keys"])
    previous = store.get("emulator_paths").get("eden", {})
    # mounts this feature added last time (first run: the ones Wolfy would have added)
    old_mounts = set(previous.get("mounts") or _session_mounts(
        {"keys": f"{DATA_DIR}/keys", "firmware": f"{DATA_DIR}/nand", "users": "", "roms": current()["roms"]}))
    new_mounts = _session_mounts(paths)
    store.put("emulator_paths", "eden", {"mounts": new_mounts})

    def wanted(app) -> list[str]:
        rom = [f"{app['rom_dir']}:{app['rom_dir']}:ro"] if app["rom_dir"] else []
        kept = [m for m in app["mounts"] + rom if m not in old_mounts and m not in new_mounts]
        return kept + new_mounts

    def eden_apps(doc):
        return [(p["id"], a) for p in wolf_config.list_profiles(doc) for a in p["apps"] if a["emulator"] == "eden"]

    def change(doc):
        for pid, app in eden_apps(doc):
            wolf_config.upsert_app(doc, pid, app["index"], {**app, "mounts": wanted(app), "rom_dir": ""})

    # restart Wolf only if config.toml really changes
    doc = wolf_config.load()
    before = wolf_config.tomlkit.dumps(doc)
    change(doc)
    changed = []
    if wolf_config.tomlkit.dumps(doc) != before:
        changed = [a["title"] for _, a in eden_apps(doc)]
        restart_wolf(change, "chemins-eden")
    return {"paths": paths, "apps_updated": changed, "eden_config_changed": ini_changed}


# ------------------------------------------------------------------ uploads

KEY_LINE = re.compile(r"^\s*[a-z0-9_]+\s*=\s*[0-9a-fA-F]+\s*$")
KEY_FILES = ("prod.keys", "title.keys")


def _check_keys(name: str, data: bytes) -> str:
    try:
        text = data.decode()
    except UnicodeDecodeError:
        raise HTTPException(400, f"{name} : fichier texte attendu")
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(("#", ";"))]
    bad = [l for l in lines if not KEY_LINE.match(l)]
    if not lines or len(bad) > len(lines) // 10:
        raise HTTPException(400, f"{name} : ce n'est pas un fichier de clés (lignes « nom = hex » attendues)")
    if name == "prod.keys" and "header_key" not in text:
        raise HTTPException(400, "prod.keys : header_key absente, fichier incomplet ?")
    return text


def upload_keys(files: list[tuple[str, bytes]]) -> dict:
    """prod.keys / title.keys, or a .zip containing them."""
    found: dict[str, bytes] = {}
    for name, data in files:
        base = Path(name).name.lower()
        if base.endswith(".zip"):
            with zipfile.ZipFile(_bytes_file(data)) as z:
                for member in z.namelist():
                    if Path(member).name.lower() in KEY_FILES:
                        found[Path(member).name.lower()] = z.read(member)
        elif base in KEY_FILES:
            found[base] = data
        else:
            raise HTTPException(400, f"{name} : prod.keys, title.keys ou .zip attendu")
    if not found:
        raise HTTPException(400, "Aucun prod.keys ni title.keys trouvé")
    texts = {name: _check_keys(name, data) for name, data in found.items()}

    keys_dir = Path(current()["keys"])
    keys_dir.mkdir(parents=True, exist_ok=True)
    backup = keys_dir / ".backups" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    for name, text in texts.items():
        dest = keys_dir / name
        if dest.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, backup / name)
        dest.write_text(text)
    _chown_like(keys_dir, keys_dir.parent)
    return {"installed": sorted(texts)}


def _bytes_file(data: bytes):
    import io
    return io.BytesIO(data)


def upload_firmware(zip_path: str) -> dict:
    """Firmware .zip (the .nca files of a Switch firmware) -> NAND system/Contents/registered."""
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise HTTPException(400, "Archive .zip invalide")
    with z:
        ncas = [m for m in z.infolist() if not m.is_dir() and m.filename.lower().endswith(".nca")]
        if len(ncas) < 20:
            raise HTTPException(400, f"Pas un firmware Switch : {len(ncas)} fichier(s) .nca dans l'archive")
        names = [Path(m.filename).name for m in ncas]
        if len(set(names)) != len(names):
            raise HTTPException(400, "Archive invalide : fichiers .nca en double")

        nand = Path(current()["firmware"])
        contents = nand / "system" / "Contents"
        contents.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="registered.new-", dir=contents))
        try:
            for m in ncas:
                with z.open(m) as src, open(staging / Path(m.filename).name, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    registered = contents / "registered"
    previous = contents / "registered.bak"
    if registered.exists():
        shutil.rmtree(previous, ignore_errors=True)
        registered.rename(previous)
    staging.rename(registered)
    registered.chmod(0o755)
    _chown_like(registered, contents)
    return {"installed": len(ncas), "backup": str(previous) if previous.exists() else None}
