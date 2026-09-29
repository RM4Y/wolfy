"""Emulator catalog: presets used to create/configure a Wolf app around a main emulator.

`build_dir` is a folder of settings.WOLF_IMAGES_DIR holding the image's Dockerfile
(custom images built locally); images without it are pulled from their registry.
"""
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

RA_HOST = settings.RETROARCH_DIR
GAMES = settings.GAMES_DIR

EMULATORS = [
    {
        "id": "eden",
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
        "name": "RetroArch",
        "systems": ["PlayStation", "PlayStation 2", "PSP", "Multi-système"],
        "description": "Interface XMB, cœurs LRPS2 / PPSSPP… Configuration, sauvegardes et BIOS "
                       "partagés avec le RetroArch flatpak de l'hôte.",
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
        "name": "Dolphin",
        "systems": ["Wii", "GameCube"],
        "description": "Image à construire (dossier images/dolphin). Les vraies Wiimotes ne "
                       "peuvent servir qu'à une session à la fois.",
        "image": "wolf-dolphin:latest",
        "build_dir": "dolphin",
        "rom_dir": f"{GAMES}/ROMS/wii",
        "mounts": [],
        "env": ["RUN_SWAY=1", *GOW_ENV],
        "multi_session": False,
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
        "name": "Steam",
        "systems": ["PC (Steam, Proton)"],
        "description": "Steam en Big Picture (image Games on Whales). Données Steam partagées entre appareils "
                       "(une seule connexion, une session à la fois), bibliothèques montées et enregistrées.",
        "image": "wolfy-steam:latest",
        "build_dir": "steam",
        "settings_page": "steam",
        "paths_page": "steam",
        "rom_dir": "",
        "mounts": [],
        "env": ["RUN_SWAY=1", *GOW_ENV],
        "multi_session": False,
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
