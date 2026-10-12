"""Automatic end of the Moonlight sessions nobody watches (Paramètres › Sessions inactives).

A session is idle while Wolf sends it no video: Moonlight closed, minimized or disconnected
without "Quitter la session" (Wolf keeps such sessions, and their app, running). The bandwidth
comes from the wolfy-net service; without it nothing is ever closed.
"""
import asyncio
import json
import time

from fastapi import HTTPException

from . import settings, store, wolf_api

DEFAULT_MINUTES = 5  # delay before closing, set in Paramètres (settings.idle_minutes)
CHECK_SECONDS = 15
VIDEO_BPS = 100_000  # below that, no picture is going out (audio alone is ~0.3 Mbit/s)

_last_active: dict[str, float] = {}  # client_id -> last time video went out (or first seen)


def enabled() -> bool:
    return bool(store.get("settings").get("idle_stop"))


def minutes() -> int:
    return int(store.get("settings").get("idle_minutes") or DEFAULT_MINUTES)


def netstat() -> dict | None:
    """Stream bandwidth per client IP, from the wolfy-net service (None: not running)."""
    try:
        d = json.loads(settings.NETSTAT.read_text())
    except (OSError, ValueError):
        return None
    if time.time() - d.get("time", 0) > 5:
        return None
    return d.get("clients", {})


def update(sessions: list[dict], net: dict | None) -> None:
    """Note which sessions are watched now; forget the ended ones."""
    now = time.time()
    keys = {str(s.get("client_id")) for s in sessions}
    for key in set(_last_active) - keys:
        del _last_active[key]
    for s in sessions:
        key = str(s.get("client_id"))
        c = (net or {}).get(s.get("client_ip"))
        # option off or no measure: never idle, so that turning the option on (or restarting
        # wolfy-net) starts the count instead of ending every unwatched session at once
        if not enabled() or net is None or key not in _last_active or (c and c["video_bps"] > VIDEO_BPS):
            _last_active[key] = now


def stop_at(session: dict) -> float | None:
    """When an idle session will be closed (None: watched, or the option is off)."""
    last = _last_active.get(str(session.get("client_id")))
    if not enabled() or last is None or time.time() - last < CHECK_SECONDS * 2:
        return None
    return last + minutes() * 60


async def _check() -> None:
    try:
        sessions = (await wolf_api.get("sessions")).get("sessions", [])
    except HTTPException:
        return  # Wolf stopped or restarting
    update(sessions, netstat())
    if not enabled():
        return
    now, delay = time.time(), minutes() * 60
    for s in sessions:
        key = str(s.get("client_id"))
        if now - _last_active.get(key, now) < delay:
            continue
        try:
            await wolf_api.post("sessions/stop", {"session_id": key})
        except HTTPException as exc:
            print(f"idle session {key} not stopped: {exc.detail}", flush=True)
            continue
        _last_active.pop(key, None)
        name = store.get("clients").get(key, {}).get("name") or s.get("client_ip", "")
        print(f"idle session of {name} ({key}) stopped after {delay // 60} min", flush=True)
        store.put("settings", "idle_last_stop", {"client": name, "app_id": s.get("app_id"), "at": now})


async def run() -> None:
    while True:
        try:
            await _check()
        except Exception as exc:  # keep watching whatever happens
            print(f"idle check failed: {exc!r}", flush=True)
        await asyncio.sleep(CHECK_SECONDS)
