"""EspBar: the ESP32 program (.bin) uploaded in Wolfy, linked to one paired Moonlight device."""
import hashlib
import time

from fastapi import HTTPException

from . import settings, store

PATH = settings.DATA_DIR / "espbar" / "firmware.bin"
MAX_SIZE = 16 * 1024 * 1024  # biggest ESP32 flash
ESP_MAGIC = 0xE9             # first byte of an ESP image (bootloader or app)
APP_OFFSET = 0x10000         # app partition of the default Arduino / PlatformIO tables
PARTITIONS_OFFSET = 0x8000   # partition table, inside a merged image
# image header chip id -> name, offset of the bootloader in flash
CHIPS = {0: ("ESP32", 0x1000), 2: ("ESP32-S2", 0x1000), 5: ("ESP32-C3", 0), 9: ("ESP32-S3", 0),
         12: ("ESP32-C2", 0), 13: ("ESP32-C6", 0), 16: ("ESP32-H2", 0)}


def _inspect(data: bytes) -> dict:
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
    raise HTTPException(400, "Ce fichier n'est pas un programme ESP32 (.bin compilé)")


def firmware() -> dict | None:
    return store.get("espbar").get("firmware") if PATH.is_file() else None


def client_id() -> str | None:
    return store.get("espbar").get("client_id")


def upload(filename: str, data: bytes) -> dict:
    """Replaces the program."""
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "Programme trop lourd (16 Mo max)")
    image = _inspect(data)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(PATH)
    meta = {
        "filename": filename or PATH.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M"),
        **image,
    }
    store.put("espbar", "firmware", meta)
    return meta


def delete() -> None:
    PATH.unlink(missing_ok=True)
    store.put("espbar", "firmware", None)


def link(client: str | None) -> None:
    store.put("espbar", "client_id", client or None)
