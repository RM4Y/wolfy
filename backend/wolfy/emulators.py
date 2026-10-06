"""Emulator catalog: presets used to create/configure a Wolf app around a main emulator.

`build_dir` is a folder of settings.WOLF_IMAGES_DIR holding the image's Dockerfile
(custom images built locally); images without it are pulled from their registry.
`cover` is the default cover of the app (Moonlight's app image), shipped in wolfy/covers and
copied into Wolf's covers folder (install_default_covers).
"""
import shutil
from pathlib import Path

from . import settings

GOW_ENV = ["GOW_REQUIRED_DEVICES=/dev/input/* /dev/dri/* /dev/nvidia*"]

BASE_CREATE_JSON = """{
  "HostConfig": {
    "IpcMode": "host",
    "Privileged": false,
    "CapAdd": ["NET_RAW", "MKNOD", "NET_ADMIN"],
    "DeviceCgroupRules": ["c 13:* rmw", "c 244:* rmw"]
  }
}
"""

# Wii / GameCube: real Wii Remotes use the host's Bluetooth, only reachable from the host
# network namespace (AF_BLUETOOTH sockets don't exist in a container's own network)
DOLPHIN_CREATE_JSON = BASE_CREATE_JSON.replace('"IpcMode": "host",', '"IpcMode": "host",\n    "NetworkMode": "host",')

RA_HOST = settings.RETROARCH_DIR
GAMES = settings.GAMES_DIR

EMULATORS = [
    {
        "id": "eden",
        "cover": "switch.png",
        "name": "Eden",
        "systems": ["Nintendo Switch"],
        "description": "Démarre sur le menu HOME Switch (qlaunch). Rejoint automatiquement le salon "
                       "local « Maison » pour le sans-fil local entre sessions.",
        "image": "wolfy-eden:latest",
        "build_dir": "eden",
        "settings_page": "eden",
        "paths_page": "eden",
        "rom_dir": f"{GAMES}/ROMS/switch",
        "mounts": [
            f"{settings.EDEN_DATA_DIR}:{settings.EDEN_DATA_DIR}:rw",
            f"{settings.EDEN_DATA_DIR}:/home/retro/.local/share/eden:rw",
            f"{settings.EDEN_CONFIG_DIR}:/eden-config-host:ro",
        ],
        "env": ["RUN_SWAY=1", *GOW_ENV],
        "multi_session": True,
    },
    {
        "id": "retroarch",
        "cover": "playstation.png",
        "name": "RetroArch",
        "systems": ["PlayStation", "PlayStation 2", "PSP", "PlayStation 3", "PS Vita"],
        "description": "Interface XMB, cœurs Beetle PSX HW / LRPS2 / PPSSPP ; PS3 (RPCS3) et PS Vita (Vita3K) "
                       "lancés depuis le XMB. Configuration, sauvegardes et BIOS partagés avec le RetroArch "
                       "flatpak de l'hôte.",
        "image": "wolfy-retroarch:latest",
        "build_dir": "retroarch",
        "settings_page": "retroarch",
        "paths_page": "retroarch",
        "rom_dir": f"{GAMES}/ROMS",
        "mounts": [
            f"{RA_HOST}:/home/retro/.var/app/org.libretro.RetroArch/config/retroarch:rw",
            f"{RA_HOST}:{RA_HOST}:rw",
            f"{settings.RETROARCH_CORES_DIR}:/app/share/libretro:ro",
        ],
        "env": ["RUN_SWAY=1", f"HOST_HOME={settings.HOST_HOME}", *GOW_ENV],
        "multi_session": True,
    },
    {
        "id": "dolphin",
        "cover": "wii.png",
        "name": "Dolphin",
        "systems": ["Wii", "GameCube"],
        "description": "Démarre sur le menu Wii (Dolphin Better Wii Menu DE : les jeux y sont des chaînes, "
                       "choisis à la Wiimote). Manettes : Wiimote + Nunchuk simulés, ou vraies "
                       "Wiimotes via le Bluetooth du serveur. Configuration, NAND et sauvegardes partagées "
                       "avec le Dolphin flatpak du PC ; les sessions lancées en même temps ont chacune leur "
                       "console (NAND et cartes mémoire à part, manettes de la session).",
        "image": "wolfy-dolphin:latest",
        "build_dir": "dolphin",
        "settings_page": "dolphin",
        "rom_dir": f"{GAMES}/ROMS/wii",
        "mounts": [
            f"{settings.DOLPHIN_DIR}/config/dolphin-emu:/dolphin-config-host:ro",
            f"{settings.DOLPHIN_DIR}/data/dolphin-emu:/home/retro/.local/share/dolphin-emu:rw",
            f"{settings.WOLFY_HOST_DIR}/config/wii/wolfy:/wolfy-config:ro",
            f"{GAMES}/ROMS/gc:{GAMES}/ROMS/gc:ro",
        ],
        "env": ["RUN_SWAY=1", *GOW_ENV],
        "base_create_json": DOLPHIN_CREATE_JSON,
        "multi_session": True,
    },
    {
        "id": "gow-retroarch",
        "name": "RetroArch (officiel GoW)",
        "systems": ["Multi-système"],
        "description": "Image officielle Games on Whales, sans configuration partagée.",
        "image": "ghcr.io/games-on-whales/retroarch:edge",
        "build_dir": None,
        "rom_dir": f"{GAMES}/ROMS",
        "mounts": [],
        "env": ["RUN_SWAY=true", *GOW_ENV],
        "multi_session": True,
    },
    {
        "id": "steam",
        "cover": "steam.png",
        "name": "Steam",
        "systems": ["PC (Steam, Proton)"],
        "description": "Steam en Big Picture (image Games on Whales). Données Steam partagées entre appareils ; "
                       "les sessions lancées en même temps ont chacune leur dossier Steam (leur compte), "
                       "bibliothèques montées et enregistrées.",
        "image": "wolfy-steam:latest",
        "build_dir": "steam",
        "settings_page": "steam",
        "paths_page": "steam",
        "rom_dir": "",
        "mounts": [],
        "env": ["RUN_SWAY=1", *GOW_ENV],
        "multi_session": True,
    },
    {
        "id": "custom",
        "name": "Personnalisé",
        "systems": [],
        "description": "N'importe quelle image Docker compatible Wolf (base-app Games on Whales).",
        "image": "",
        "build_dir": None,
        "rom_dir": "",
        "mounts": [],
        "env": ["RUN_SWAY=1", *GOW_ENV],
        "multi_session": True,
    },
]

BY_ID = {e["id"]: e for e in EMULATORS}


def guess(image: str) -> str:
    """Emulator preset matching an app image (for apps not created by Wolfy)."""
    for emu in EMULATORS:
        if emu["image"] and emu["image"] == image:
            return emu["id"]
    return "custom"


DEFAULT_COVERS = Path(__file__).parent / "covers"


def cover_path(emu: dict) -> str:
    """Default cover of an emulator's apps, as Wolf sees it ('' if none)."""
    return str(settings.WOLF_COVERS_DIR / emu["cover"]) if emu.get("cover") else ""


def install_default_covers() -> None:
    """Copy the default covers into Wolf's covers folder (never over an existing file)."""
    settings.WOLF_COVERS_DIR.mkdir(parents=True, exist_ok=True)
    for src in DEFAULT_COVERS.glob("*.png"):
        dest = settings.WOLF_COVERS_DIR / src.name
        if not dest.exists():
            shutil.copyfile(src, dest)
            dest.chmod(0o644)

