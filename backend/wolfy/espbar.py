"""EspBar: the ESP32 programs shipped with Wolfy (espbar/firmware.bin for one ESP32,
firmware-dual.bin + firmware-bt.bin for two), injected from the browser, and the EspBar boards: the paired
Moonlight device each is linked to."""
import hashlib
import json
import secrets
import time

from . import settings, store

# one ESP32 (Wi-Fi + Bluetooth), or two: the Wi-Fi one, which updates the Bluetooth one itself,
# and the Bluetooth one (injected once, when its GPIO0 isn't wired to the Wi-Fi one)
VARIANTS = {"single": settings.ESPBAR_FIRMWARE,
            "dual": settings.ESPBAR_FIRMWARE.with_name("firmware-dual.bin"),
            "bt": settings.ESPBAR_FIRMWARE.with_name("firmware-bt.bin")}
ESP_MAGIC = 0xE9             # first byte of an ESP image (bootloader or app)
APP_OFFSET = 0x10000         # app partition of the default Arduino / PlatformIO tables
PARTITIONS_OFFSET = 0x8000   # partition table, inside a merged image
CONFIG_OFFSET = 0x3FF000     # "espbar" partition (espbar/firmware/partitions.csv): Wi-Fi, Wolfy
# image header chip id -> name, offset of the bootloader in flash
CHIPS = {0: ("ESP32", 0x1000), 2: ("ESP32-S2", 0x1000), 5: ("ESP32-C3", 0), 9: ("ESP32-S3", 0),
         12: ("ESP32-C2", 0), 13: ("ESP32-C6", 0), 16: ("ESP32-H2", 0)}


def _inspect(data: bytes) -> dict | None:
    """Chip and flash address of a .bin: merged image (bootloader + partitions + app,
    written at 0) or app alone (written at 0x10000)."""
    merged = data[PARTITIONS_OFFSET:PARTITIONS_OFFSET + 2] == b"\xaa\x50"
    for start in (0, 0x1000) if merged else (0,):
        if len(data) > start + 13 and data[start] == ESP_MAGIC:
            chip_id = int.from_bytes(data[start + 12:start + 14], "little")
            chip, boot = CHIPS.get(chip_id, (None, None))
            if merged and boot not in (None, start):
                continue
            return {"chip_id": chip_id, "chip": chip, "merged": merged, "offset": 0 if merged else APP_OFFSET}
    return None


def firmware(variant: str) -> dict | None:
    """The program of <variant> (VARIANTS), or None while it is not built yet."""
    path = VARIANTS[variant]
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not (image := _inspect(data)):
        return None
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "built_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
        **image,
        "config_offset": CONFIG_OFFSET,
    }


def token() -> str:
    """Token of the ESP32 for Wolfy's relay (generated once, in the data dir)."""
    path = settings.DATA_DIR / "espbar.token"
    if not path.exists():
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()


def wifi() -> dict:
    return store.get("espbar").get("wifi") or {"ssid": "", "password": "", "url": ""}


def config_blob(ssid: str, password: str, url: str) -> bytes:
    """Contents of the "espbar" partition, written next to the program (firmware/main/config.c):
    Wi-Fi, and Wolfy's WebSocket (wss://wolfy.rm4.fr/api/espbar/ws or ws://<lan ip>:8420/...)."""
    store.put("espbar", "wifi", {"ssid": ssid, "password": password, "url": url})
    data = {"ssid": ssid, "password": password, "url": url, "token": token()}
    return b"EB01" + json.dumps(data).encode() + b"\0"


# The EspBar boards, known by their chip's base MAC ("id" of their HELLO, read by the browser
# at injection): {key: {"client_id"}}. A device has one EspBar at most (each fills the
# Wii Remote slots 1-4 of its Dolphin).

def boards() -> dict[str, dict]:
    return store.get("espbar_boards")


def board_name(key: str) -> str:
    return f"EspBar {key}"


def register(key: str) -> None:
    """An EspBar connected: known from now on (the first one takes the former single link)."""
    if key in boards():
        return
    legacy = store.get("espbar").get("client_id")
    store.put("espbar_boards", key, {"client_id": None})
    if legacy:
        store.put("espbar", "client_id", None)
        save(key, legacy)


def save(key: str, client_id: str | None) -> None:
    """Give an EspBar a device (taken from the EspBar that had it), or none."""
    if client_id:
        for other, b in boards().items():
            if other != key and b.get("client_id") == client_id:
                store.put("espbar_boards", other, {**b, "client_id": None})
    store.put("espbar_boards", key, {**boards().get(key, {}), "client_id": client_id or None})


def forget(key: str) -> None:
    store.put("espbar_boards", key, None)


def unlink_client(client_id: str) -> None:
    """The device was unpaired: no EspBar for it any more."""
    for key, b in boards().items():
        if b.get("client_id") == client_id:
            store.put("espbar_boards", key, {**b, "client_id": None})
