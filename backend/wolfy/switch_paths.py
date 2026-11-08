"""Switch (Eglantine) keys, firmware and games: fixed layout in the Wolfy project, the data folder
being mounted as Eglantine's data dir (~/.local/share/eden) in the session:

    config/switch/data/keys     prod.keys, title.keys
    config/switch/data/nand     NAND: firmware (system/Contents/registered), accounts, saves
    $WOLFY_GAMES_DIR/ROMS/switch, ROMS/switch2   Switch 1 and Switch 2 games (read-only)

Uploads reuse Eden's (eden_paths), pointed at these folders.
"""
from . import eden_paths, settings

DATA_DIR = f"{settings.WOLFY_HOST_DIR}/config/switch/data"
KEYS_DIR = f"{DATA_DIR}/keys"
NAND_DIR = f"{DATA_DIR}/nand"
ROMS_DIRS = [f"{settings.GAMES_DIR}/ROMS/switch", f"{settings.GAMES_DIR}/ROMS/switch2"]


def status() -> dict:
    host = eden_paths.host
    keys = host(KEYS_DIR)
    found = [k for k in ("prod.keys", "title.keys") if (keys / k).is_file()]
    reg = host(NAND_DIR) / "system" / "Contents" / "registered"
    ncas = len(list(reg.glob("*"))) if reg.is_dir() else 0
    version = eden_paths._firmware_version(DATA_DIR)
    games = 0
    for roms in map(host, ROMS_DIRS):
        if roms.is_dir():
            # dumps (.xci, .nsp, .nup…) and extracted titles (a folder holding exefs/)
            games += sum(1 for f in roms.rglob("*") if f.suffix.lower() in (*eden_paths.GAME_EXT, ".nup")
                         or (f.is_dir() and f.name.lower() == "exefs"))
    saves = host(NAND_DIR) / "user" / "save"
    n_saves = len([p for p in saves.glob("*/*/*") if p.is_dir()]) if saves.is_dir() else 0
    return {
        "keys": {"ok": "prod.keys" in found, "exists": keys.is_dir(), "path": KEYS_DIR,
                 "detail": ", ".join(found) or "aucune clé trouvée"},
        "firmware": {"ok": ncas > 0, "exists": True, "path": NAND_DIR,
                     "detail": (f"firmware {version} · " if version and ncas else "")
                               + (f"{ncas} fichiers système" if ncas else "aucun firmware installé")},
        "roms": {"ok": games > 0, "exists": any(host(d).is_dir() for d in ROMS_DIRS),
                 "path": " + ".join(ROMS_DIRS), "detail": f"{games} jeu(x)"},
        "saves": {"ok": True, "exists": True, "detail": f"{n_saves} sauvegarde(s) de jeux"},
    }


def upload_keys(files: list[tuple[str, bytes]]) -> dict:
    return eden_paths.upload_keys(files, KEYS_DIR)


def upload_firmware(zip_path: str) -> dict:
    return eden_paths.upload_firmware(zip_path, NAND_DIR)
