"""Wolfy's own metadata (client names, app ↔ emulator links), in a small JSON file."""
import json
import threading
from typing import Any

from . import settings

_lock = threading.Lock()
_PATH = settings.DATA_DIR / "wolfy.json"


def _read() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except FileNotFoundError:
        return {}


def get(section: str) -> dict[str, Any]:
    with _lock:
        return _read().get(section, {})


def put(section: str, key: str, value: Any | None) -> None:
    """Set (or delete, with value=None) one entry of a section."""
    with _lock:
        data = _read()
        entries = data.setdefault(section, {})
        if value is None:
            entries.pop(key, None)
        else:
            entries[key] = value
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(_PATH)
