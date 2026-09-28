"""Read/write Wolf's config.toml (profiles and their apps), preserving its formatting.

Wolf only reads config.toml at startup and rewrites it on its own (pairing, exit),
so writes go through docker_ops.with_wolf_stopped(): stop Wolf, re-read the file,
change it, write it, start Wolf again.
"""
import re
import shutil
from datetime import datetime

import tomlkit
from fastapi import HTTPException
from tomlkit.items import AoT, Table

from . import emulators, settings, store

BACKUP_DIR = settings.WOLF_CONFIG.parent / "wolfy-backups"
KEEP_BACKUPS = 30


def load() -> tomlkit.TOMLDocument:
    return tomlkit.parse(settings.WOLF_CONFIG.read_text())


def backup(reason: str) -> str:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    slug = re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")[:40]
    dest = BACKUP_DIR / f"config.toml.{stamp}.{slug}"
    shutil.copy2(settings.WOLF_CONFIG, dest)
    for old in sorted(BACKUP_DIR.glob("config.toml.*"))[:-KEEP_BACKUPS]:
        old.unlink()
    return dest.name


def save(doc: tomlkit.TOMLDocument, reason: str) -> None:
    backup(reason)
    tmp = settings.WOLF_CONFIG.with_suffix(".wolfy-tmp")
    tmp.write_text(tomlkit.dumps(doc))
    tmp.replace(settings.WOLF_CONFIG)


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    return [
        {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
        for p in sorted(BACKUP_DIR.glob("config.toml.*"), reverse=True)
    ]


def restore_backup(name: str) -> None:
    src = BACKUP_DIR / name
    if "/" in name or not src.is_file():
        raise HTTPException(404, "Sauvegarde introuvable")
    backup("avant-restauration")
    shutil.copy2(src, settings.WOLF_CONFIG)


# ---------------------------------------------------------------- profiles / apps

def _profiles(doc) -> AoT:
    return doc.get("profiles", [])


def _profile(doc, profile_id: str):
    for prof in _profiles(doc):
        if prof.get("id") == profile_id:
            return prof
    raise HTTPException(404, f"Profil {profile_id} introuvable")


def _app(doc, profile_id: str, index: int):
    apps = _profile(doc, profile_id).get("apps", [])
    if not 0 <= index < len(apps):
        raise HTTPException(404, "Application introuvable (la config a peut-être changé, recharge la page)")
    return apps[index]


def _split_rom_mount(mounts: list[str], rom_dir: str) -> tuple[str, list[str]]:
    """Separate the ROM folder mount (`dir:dir:ro`) from the other mounts."""
    if rom_dir:
        rom_mount = f"{rom_dir}:{rom_dir}:ro"
        if rom_mount in mounts:
            return rom_dir, [m for m in mounts if m != rom_mount]
    return "", mounts


def app_to_dict(app, index: int, profile_id: str) -> dict:
    runner = app.get("runner", {})
    image = str(runner.get("image", ""))
    name = str(runner.get("name", ""))
    meta = store.get("apps").get(name, {})
    emulator = meta.get("emulator") or emulators.guess(image)
    mounts = [str(m) for m in runner.get("mounts", [])]
    rom_dir = meta.get("rom_dir") or emulators.BY_ID.get(emulator, {}).get("rom_dir", "")
    rom_dir, mounts = _split_rom_mount(mounts, rom_dir)
    return {
        "profile_id": profile_id,
        "index": index,
        "title": str(app.get("title", "")),
        "icon": str(app.get("icon_png_path", "")),
        "start_virtual_compositor": bool(app.get("start_virtual_compositor", True)),
        "runner_type": str(runner.get("type", "docker")),
        "runner_name": name,
        "emulator": emulator,
        "image": image,
        "rom_dir": rom_dir,
        "mounts": mounts,
        "env": [str(e) for e in runner.get("env", [])],
        "devices": [str(d) for d in runner.get("devices", [])],
        "ports": [str(p) for p in runner.get("ports", [])],
        "base_create_json": str(runner.get("base_create_json", "")),
        "notes": meta.get("notes", ""),
    }


def list_profiles(doc) -> list[dict]:
    out = []
    for prof in _profiles(doc):
        pid = str(prof.get("id"))
        out.append({
            "id": pid,
            "name": str(prof.get("name", "Moonlight" if pid == settings.DEFAULT_PROFILE else pid)),
            "moonlight": pid == settings.DEFAULT_PROFILE,
            "apps": [app_to_dict(a, i, pid) for i, a in enumerate(prof.get("apps", []))],
        })
    return out


def _array(values: list[str]):
    arr = tomlkit.array()
    for v in values:
        arr.append(v)
    if len(values) > 1:
        arr.multiline(True)
    return arr


def runner_name_for(title: str) -> str:
    return "Wolf" + (re.sub(r"[^A-Za-z0-9]+", "", title.title()) or "App")


def _set(table: Table, key: str, value) -> None:
    """Assign only on change, so untouched values keep Wolf's original formatting."""
    current = table.get(key)
    plain = current.unwrap() if hasattr(current, "unwrap") else current
    wanted = value.unwrap() if hasattr(value, "unwrap") else value
    if key not in table or plain != wanted:
        table[key] = value


def _fill(app: Table, data: dict) -> None:
    """Write the fields Wolfy manages; unknown keys of an existing app are kept."""
    if data["runner_type"] != "docker":
        raise HTTPException(400, "Seuls les runners docker sont modifiables depuis Wolfy")
    if not data["title"].strip():
        raise HTTPException(400, "Titre obligatoire")
    if not data["image"].strip():
        raise HTTPException(400, "Image Docker obligatoire")
    _set(app, "title", data["title"].strip())
    if data["icon"]:
        _set(app, "icon_png_path", data["icon"])
    elif "icon_png_path" in app:
        del app["icon_png_path"]
    _set(app, "start_virtual_compositor", data["start_virtual_compositor"])

    runner = app.get("runner")
    if runner is None:
        runner = tomlkit.table()
        app["runner"] = runner
    mounts = [m for m in data["mounts"] if m.strip()]
    if data["rom_dir"].strip():
        rom = data["rom_dir"].strip().rstrip("/")
        mounts.append(f"{rom}:{rom}:ro")
    _set(runner, "type", "docker")
    _set(runner, "name", data["runner_name"].strip() or runner_name_for(data["title"]))
    _set(runner, "image", data["image"].strip())
    _set(runner, "mounts", _array(mounts))
    _set(runner, "env", _array([e for e in data["env"] if e.strip()]))
    _set(runner, "devices", _array([d for d in data["devices"] if d.strip()]))
    _set(runner, "ports", _array([p for p in data["ports"] if p.strip()]))
    _set(runner, "base_create_json", tomlkit.string(
        data["base_create_json"].strip() + "\n", literal=True, multiline=True))


def upsert_app(doc, profile_id: str, index: int | None, data: dict) -> str:
    prof = _profile(doc, profile_id)
    if index is None:
        app = tomlkit.table()
        _fill(app, data)
        if "apps" not in prof:
            prof["apps"] = tomlkit.aot()
        prof["apps"].append(app)
    else:
        app = _app(doc, profile_id, index)
        _fill(app, data)
    name = str(app["runner"]["name"])
    store.put("apps", name, {
        "emulator": data["emulator"],
        "rom_dir": data["rom_dir"].strip().rstrip("/"),
        "notes": data.get("notes", ""),
    })
    return name


def delete_app(doc, profile_id: str, index: int) -> None:
    apps = _profile(doc, profile_id)["apps"]
    _app(doc, profile_id, index)
    del apps[index]


def move_app(doc, profile_id: str, index: int, delta: int) -> None:
    apps = _profile(doc, profile_id)["apps"]
    target = index + delta
    _app(doc, profile_id, index)
    if not 0 <= target < len(apps):
        return
    items = [apps[i] for i in range(len(apps))]
    items[index], items[target] = items[target], items[index]
    new = tomlkit.aot()
    for item in items:
        new.append(item)
    _profile(doc, profile_id)["apps"] = new


def all_runner_names(doc) -> set[str]:
    return {
        str(a.get("runner", {}).get("name", ""))
        for prof in _profiles(doc) for a in prof.get("apps", [])
    } - {""}


def all_images(doc) -> set[str]:
    return {
        str(a.get("runner", {}).get("image", ""))
        for prof in _profiles(doc) for a in prof.get("apps", [])
    } - {""}


def hostname(doc) -> str:
    return str(doc.get("hostname", "Wolf"))
