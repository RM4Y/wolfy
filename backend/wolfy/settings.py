"""Runtime settings, all overridable through environment variables."""
import os
import secrets
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


DATA_DIR = Path(_env("WOLFY_DATA", "/data"))
ADMIN_PASSWORD = _env("WOLFY_ADMIN_PASSWORD", "")
SESSION_HOURS = int(_env("WOLFY_SESSION_HOURS", "168"))

# Wolf side
WOLF_SOCKET = _env("WOLF_SOCKET", "/var/run/wolf/wolf.sock")
WOLF_CONTAINER = _env("WOLF_CONTAINER", "wolf")
WOLF_STATE_DIR = Path(_env("WOLF_STATE_DIR", "/opt/stacks/config/wolf"))
WOLF_CONFIG = Path(_env("WOLF_CONFIG", str(WOLF_STATE_DIR / "cfg" / "config.toml")))
WOLF_COVERS_DIR = Path(_env("WOLF_COVERS_DIR", str(WOLF_STATE_DIR / "covers")))
# build contexts of the custom app images (one sub-folder per image): Wolfy's own
# images/ folder first, then the Wolf stack's
WOLFY_IMAGES_DIR = Path(_env("WOLFY_IMAGES_DIR", str(Path(__file__).resolve().parents[2] / "images")))
WOLF_IMAGES_DIR = Path(_env("WOLF_IMAGES_DIR", "/opt/stacks/wolf/images"))
# home of the host user running the PC's emulators (flatpak RetroArch, Eden)
HOST_HOME = _env("HOST_HOME", str(Path.home()))
# games disk: default ROM folders and Steam library
GAMES_DIR = _env("WOLFY_GAMES_DIR", "/mnt/games")
# emulator configs shared by the host and every Wolf session
# the host's flatpak RetroArch (retroarch.cfg shared with the PlayStation sessions)
RETROARCH_DIR = _env("RETROARCH_DIR", f"{HOST_HOME}/.var/app/org.libretro.RetroArch/config/retroarch")
# the flatpak RetroArch's cores, mounted read-only in the PlayStation sessions
RETROARCH_CORES_DIR = _env(
    "RETROARCH_CORES_DIR",
    f"{HOST_HOME}/.local/share/flatpak/app/org.libretro.RetroArch/current/active/files/share/libretro")
# the host's flatpak Dolphin (config copied into the Wii sessions, NAND / saves shared)
DOLPHIN_DIR = _env("DOLPHIN_DIR", f"{HOST_HOME}/.var/app/org.DolphinEmu.dolphin-emu")
EDEN_DATA_DIR = _env("EDEN_DATA_DIR", f"{HOST_HOME}/.local/share/eden")
EDEN_CONFIG_DIR = _env("EDEN_CONFIG_DIR", f"{HOST_HOME}/.config/eden")
EDEN_CONFIG = Path(_env("EDEN_CONFIG", f"{EDEN_CONFIG_DIR}/qt-config.ini"))
# Moonlight clients only see this profile
DEFAULT_PROFILE = _env("WOLF_DEFAULT_PROFILE", "moonlight-profile-id")

# host path of this project (emulator data lives in <it>/config, mounted at the same path)
WOLFY_HOST_DIR = _env("WOLFY_DIR", str(Path(__file__).resolve().parents[2]))

# read-only view of the host filesystem (emulator paths: checks and folder picker)
HOST_ROOT = Path(_env("WOLFY_HOST_ROOT", "/host"))

# host port of Wolfy, called back by the Switch sessions (quit combo)
PUBLIC_PORT = int(_env("WOLFY_PUBLIC_PORT", "8420"))

# the EspBar's ESP32 program, injected from the browser (espbar/ in this project)
ESPBAR_FIRMWARE = Path(_env("WOLFY_ESPBAR_FIRMWARE", str(Path(__file__).resolve().parents[2] / "espbar" / "firmware.bin")))

STATIC_DIR = Path(_env("WOLFY_STATIC", str(Path(__file__).resolve().parent.parent / "static")))


def secret_key() -> str:
    """Cookie signing key: WOLFY_SECRET, else generated once and kept in the data dir."""
    if key := os.environ.get("WOLFY_SECRET"):
        return key
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip()


def hook_token() -> str:
    """Token the Wolf sessions send to Wolfy's hooks (generated once, in the data dir)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "hook.token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()
