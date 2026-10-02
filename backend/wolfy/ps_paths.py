"""PS3 (RPCS3) and PS Vita (Vita3K) in the PlayStation app: firmware, games, installs.

Data folders (ps_config.RPCS3_DIR / VITA3K_DIR, in the project's config/playstation) are mounted
in every PlayStation session (ra_paths._session_mounts). Games:
  PS3   disc game folders (<game>/PS3_GAME/…, decrypted) in the ROM folders, used in place;
        PSN games / updates / DLC (.pkg + .rap licence) installed into RPCS3's dev_hdd0
  Vita  installed into Vita3K's ux0: .vpk / .zip / folder dumps (copied), .pkg + zRIF licence
Firmware (PS3UPDAT.PUP, PSVUPDAT.PUP) and .pkg installs run the emulator itself, in a one-shot
container of the PlayStation image (docker_ops.run_container) as the owner of the data folder.
"""
import os
import re
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path

from fastapi import HTTPException

from . import docker_ops, settings
from .eden_paths import _chown_like, host
from .ps_config import PS_DIR, RPCS3_DIR, VITA3K_DIR

IMAGE = "wolfy-retroarch:latest"
UPLOADS = PS_DIR / ".uploads"
# where the data folders are mounted in the image (sessions and install containers)
RPCS3_MOUNT = "/home/retro/.config/rpcs3"
VITA3K_MOUNT = "/home/retro/.local/share/Vita3K"
VITA_FS = VITA3K_DIR / "fs"
INSTALLABLE = (".pkg", ".rap", ".vpk", ".zip", ".pup")


def session_mounts() -> list[str]:
    return [f"{RPCS3_DIR}:{RPCS3_MOUNT}:rw", f"{VITA3K_DIR}:{VITA3K_MOUNT}:rw"]


def ensure_dirs() -> None:
    for d in (RPCS3_DIR, VITA3K_DIR):
        if not d.is_dir():
            d.mkdir(parents=True)
            _chown_like(d, PS_DIR)


# ------------------------------------------------------------------ PARAM.SFO / pkg

def parse_sfo(data: bytes) -> dict:
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


def read_sfo(path: Path) -> dict:
    try:
        return parse_sfo(path.read_bytes())
    except (OSError, ValueError, struct.error):
        return {}


def pkg_platform(path: Path) -> str | None:
    """'ps3' or 'vita' from a .pkg header (type 1 = PS3, 2 = PSP / PS Vita)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    if head[:4] != b"\x7fPKG":
        return None
    return {1: "ps3", 2: "vita"}.get(head[7])


# ------------------------------------------------------------------ status

def ps3_firmware() -> str | None:
    p = RPCS3_DIR / "dev_flash" / "vsh" / "etc" / "version.txt"
    if not p.is_file():
        return None
    m = re.search(r"release:([\d.]+)", p.read_text(errors="replace"))
    return m.group(1) if m else "installé"


def vita_firmware() -> str | None:
    if not (VITA_FS / "vs0" / "vsh").is_dir() or not (VITA_FS / "os0").is_dir():
        return None
    p = VITA_FS / "vs0" / "vsh" / "etc" / "version.txt"
    m = re.search(r"([\d]+\.[\d]+)", p.read_text(errors="replace")) if p.is_file() else None
    return m.group(1) if m else "installé"


def ps3_games(rom_dirs: list[str]) -> list[dict]:
    games = {}
    for d in rom_dirs:
        root = host(d)
        if not root.is_dir():
            continue
        try:
            entries = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            continue
        for game in entries:
            for base in (game / "PS3_GAME", game):
                if (base / "USRDIR" / "EBOOT.BIN").is_file() and (base / "PARAM.SFO").is_file():
                    sfo = read_sfo(base / "PARAM.SFO")
                    games.setdefault(sfo.get("TITLE_ID") or game.name, {
                        "id": sfo.get("TITLE_ID", ""), "title": sfo.get("TITLE") or game.name,
                        "where": "disque", "path": "/" + str(game.relative_to(settings.HOST_ROOT))})
                    break
    hdd = RPCS3_DIR / "dev_hdd0" / "game"
    if hdd.is_dir():
        for game in sorted(p for p in hdd.iterdir() if p.is_dir()):
            sfo = read_sfo(game / "PARAM.SFO")
            if sfo.get("CATEGORY") == "HG" and (game / "USRDIR" / "EBOOT.BIN").is_file():
                games.setdefault(sfo.get("TITLE_ID") or game.name, {
                    "id": sfo.get("TITLE_ID", game.name), "title": sfo.get("TITLE") or game.name,
                    "where": "installé (dev_hdd0)", "path": str(game)})
    return sorted(games.values(), key=lambda g: g["title"].lower())


def vita_games() -> list[dict]:
    apps = VITA_FS / "ux0" / "app"
    out = []
    if apps.is_dir():
        for app in sorted(p for p in apps.iterdir() if p.is_dir()):
            sfo = read_sfo(app / "sce_sys" / "param.sfo")
            if (app / "eboot.bin").is_file():
                out.append({"id": app.name, "title": sfo.get("TITLE") or app.name, "where": "installé (ux0)",
                            "path": str(app)})
    return sorted(out, key=lambda g: g["title"].lower())


def installables(rom_dirs: list[str]) -> list[dict]:
    """Files of the ROM folders that can be installed (first two folder levels)."""
    out = []
    for d in rom_dirs:
        root = host(d)
        if not root.is_dir():
            continue
        for p in sorted([*root.glob("*"), *root.glob("*/*")]):
            name = p.name.lower()
            kind = None
            if p.is_file() and name.endswith(".pkg"):
                kind = {"ps3": "ps3-pkg", "vita": "vita-pkg"}.get(pkg_platform(p))
            elif p.is_file() and name.endswith(".rap"):
                kind = "ps3-rap"
            elif p.is_file() and name.endswith((".vpk", ".zip")):
                try:
                    with zipfile.ZipFile(p) as z:
                        kind = "vita-archive" if any(n.lower().endswith("sce_sys/param.sfo") for n in z.namelist()) else None
                except (zipfile.BadZipFile, OSError):
                    kind = None
            elif p.is_file() and name == "ps3updat.pup":
                kind = "ps3-firmware"
            elif p.is_file() and name in ("psvupdat.pup", "psp2updat.pup"):
                kind = "vita-firmware"
            elif p.is_dir() and (p / "sce_sys" / "param.sfo").is_file() and (p / "eboot.bin").is_file():
                kind = "vita-folder"
            if kind:
                out.append({"path": "/" + str(p.relative_to(settings.HOST_ROOT)), "name": p.name, "kind": kind,
                            "size": p.stat().st_size if p.is_file() else None})
    return out


def status(rom_dirs: list[str]) -> dict:
    return {
        "ps3": {"firmware": ps3_firmware(), "games": ps3_games(rom_dirs)},
        "vita": {"firmware": vita_firmware(), "games": vita_games()},
        "installables": installables(rom_dirs),
    }


# ------------------------------------------------------------------ installs

def _owner(path: Path) -> str:
    st = path.stat()
    return f"{st.st_uid}:{st.st_gid}"


def _run(job, script: str, file: str | None) -> None:
    """Run SCRIPT (bash) in a one-shot PlayStation container, data folders mounted as in a session."""
    ensure_dirs()
    mounts = session_mounts()
    if file:
        mounts.append(f"{file}:{file}:ro")
    docker_ops.run_container(job, IMAGE, ["/bin/bash", "-c", script], mounts, user=_owner(PS_DIR),
                             environment={"HOME": "/home/retro", "XDG_CONFIG_HOME": "/home/retro/.config"})


def _q(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def install_ps3_firmware(job, file: str) -> None:
    job.log(f"Installation du firmware PS3 : {file}")
    _run(job, f"/opt/rpcs3/AppRun --headless --installfw {_q(file)}", file)
    version = ps3_firmware()
    if not version:
        raise RuntimeError("RPCS3 n'a pas installé le firmware (fichier PS3UPDAT.PUP valide ?)")
    job.log(f"Firmware PS3 {version} installé.")


def install_vita_firmware(job, file: str) -> None:
    job.log(f"Installation du firmware PS Vita : {file}")
    _run(job, f"xvfb-run -a /opt/vita3k/usr/bin/Vita3K --firmware {_q(file)}", file)
    job.log(f"Firmware : {vita_firmware() or 'non détecté (fichier valide ?)'}")


def install_ps3_pkg(job, file: str) -> None:
    job.log(f"Installation du pkg PS3 : {file}")
    before = {g["id"] for g in ps3_games([])}
    _run(job, f"/opt/rpcs3/AppRun --headless --installpkg {_q(file)}", file)
    new = [g["title"] for g in ps3_games([]) if g["id"] not in before]
    job.log(f"Installé : {', '.join(new)}" if new else "Paquet installé (mise à jour / DLC, ou jeu déjà présent).")


def install_ps3_rap(job, file: str) -> None:
    dest = RPCS3_DIR / "dev_hdd0" / "home" / "00000001" / "exdata"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(host(file), dest / Path(file).name)
    _chown_like(RPCS3_DIR / "dev_hdd0", RPCS3_DIR)
    job.log(f"Licence {Path(file).name} copiée dans dev_hdd0/home/00000001/exdata.")


def install_vita_pkg(job, file: str, zrif: str) -> None:
    zrif = zrif.strip()
    if not re.fullmatch(r"[A-Za-z0-9+/=_-]{20,}", zrif):
        raise RuntimeError("zRIF manquant ou invalide (licence du jeu, en base64)")
    job.log(f"Installation du pkg PS Vita : {file}")
    before = {g["id"] for g in vita_games()}
    _run(job, f"xvfb-run -a /opt/vita3k/usr/bin/Vita3K --pkg {_q(file)} --zrif {_q(zrif)}", file)
    new = [g["title"] for g in vita_games() if g["id"] not in before]
    job.log(f"Installé : {', '.join(new)}" if new else "Paquet installé (mise à jour / DLC, ou jeu déjà présent).")


def _vita_dest(sfo: dict) -> Path:
    title_id, category = sfo.get("TITLE_ID", ""), str(sfo.get("CATEGORY", "gd"))
    if not re.fullmatch(r"[A-Z]{4}\d{5}", title_id):
        raise RuntimeError(f"TITLE_ID invalide dans param.sfo : {title_id!r}")
    if category.startswith("gp"):
        return VITA_FS / "ux0" / "patch" / title_id
    if category == "ac":
        return VITA_FS / "ux0" / "addcont" / title_id / sfo.get("CONTENT_ID", title_id)[20:]
    return VITA_FS / "ux0" / "app" / title_id


def _vita_license(sfo: dict, work_bin: bytes | None, job) -> None:
    """NoNpDrm dumps: sce_sys/package/work.bin = the game's licence, where Vita3K looks for it."""
    if not work_bin:
        return
    content_id = sfo.get("CONTENT_ID") or ""
    title_id = sfo.get("TITLE_ID", "")
    if not content_id:
        return
    dest = VITA_FS / "ux0" / "license" / title_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{content_id}.rif").write_bytes(work_bin)
    job.log(f"Licence {content_id}.rif installée.")


def install_vita_archive(job, file: str) -> None:
    src = host(file)
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        sfo_name = min((n for n in names if n.lower().endswith("sce_sys/param.sfo")), key=len, default=None)
        if not sfo_name:
            raise RuntimeError("Pas de sce_sys/param.sfo dans l'archive")
        prefix = sfo_name[:-len("sce_sys/param.sfo")]
        sfo = parse_sfo(z.read(sfo_name))
        dest = _vita_dest(sfo)
        job.log(f"{sfo.get('TITLE', '?')} ({sfo.get('TITLE_ID')}) -> {dest.relative_to(VITA3K_DIR)}")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        members = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
        for i, name in enumerate(members, 1):
            rel = Path(name[len(prefix):])
            if rel.is_absolute() or ".." in rel.parts:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as fsrc, open(target, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, 1 << 20)
            if i % 500 == 0:
                job.log(f"{i}/{len(members)} fichiers…")
        work = prefix + "sce_sys/package/work.bin"
        _vita_license(sfo, z.read(work) if work in names else None, job)
    _chown_like(VITA_FS, VITA3K_DIR)
    job.log(f"{len(members)} fichiers installés.")


def install_vita_folder(job, folder: str) -> None:
    src = host(folder)
    sfo = read_sfo(src / "sce_sys" / "param.sfo")
    dest = _vita_dest(sfo)
    job.log(f"{sfo.get('TITLE', '?')} ({sfo.get('TITLE_ID')}) -> {dest.relative_to(VITA3K_DIR)}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    work = src / "sce_sys" / "package" / "work.bin"
    _vita_license(sfo, work.read_bytes() if work.is_file() else None, job)
    _chown_like(VITA_FS, VITA3K_DIR)
    job.log("Dossier copié.")


INSTALLERS = {
    "ps3-firmware": install_ps3_firmware, "ps3-pkg": install_ps3_pkg, "ps3-rap": install_ps3_rap,
    "vita-firmware": install_vita_firmware, "vita-archive": install_vita_archive, "vita-folder": install_vita_folder,
}


def install(path: str, zrif: str, rom_dirs: list[str]):
    """Install a file listed by installables() (only those: no arbitrary host path)."""
    item = next((i for i in installables(rom_dirs) if i["path"] == path), None)
    if not item:
        raise HTTPException(404, "Fichier introuvable dans les dossiers de jeux")
    kind = item["kind"]
    if kind == "vita-pkg":
        return docker_ops.run_job(f"Installation {item['name']}", lambda job: install_vita_pkg(job, path, zrif))
    return docker_ops.run_job(f"Installation {item['name']}", lambda job: INSTALLERS[kind](job, path))


def upload_firmware(system: str, tmp_path: str):
    """Firmware sent from the browser: kept in config/playstation/.uploads during the install."""
    if system not in ("ps3", "vita"):
        raise HTTPException(404, "Système inconnu")
    with open(tmp_path, "rb") as f:
        if f.read(5) != b"SCEUF":
            raise HTTPException(400, "Ce n'est pas un fichier firmware Sony (.PUP)")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    _chown_like(UPLOADS, PS_DIR)
    dest = UPLOADS / ("PS3UPDAT.PUP" if system == "ps3" else "PSVUPDAT.PUP")
    shutil.move(tmp_path, dest)
    os.chmod(dest, 0o644)

    def work(job):
        try:
            (install_ps3_firmware if system == "ps3" else install_vita_firmware)(job, str(dest))
        finally:
            dest.unlink(missing_ok=True)

    return docker_ops.run_job(f"Firmware {'PS3' if system == 'ps3' else 'PS Vita'}", work)


def upload_tmp() -> str:
    """Temporary file for an upload, on the same disk as config/playstation (cheap move)."""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=UPLOADS, suffix=".part")
    os.close(fd)
    return path
