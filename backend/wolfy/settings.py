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
# build contexts of the custom app images (one sub-folder per image)
WOLF_IMAGES_DIR = Path(_env("WOLF_IMAGES_DIR", "/opt/stacks/wolf/images"))
# emulator configs shared by the host and every Wolf session
EDEN_CONFIG = Path(_env("EDEN_CONFIG", "/home/remy/.config/eden/qt-config.ini"))
# Moonlight clients only see this profile
DEFAULT_PROFILE = _env("WOLF_DEFAULT_PROFILE", "moonlight-profile-id")

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
