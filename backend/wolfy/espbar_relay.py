"""EspBar relay between the ESP32 (Wii Remotes over Bluetooth) and the Dolphin of the linked
device's Wii session (images/dolphin/espbar/IOEspBar.cpp). The ESP32 comes through a WebSocket
on Wolfy's own address (/api/espbar/ws: wss://wolfy.rm4.fr through SWAG, or ws://<lan ip>:8420),
the sessions' Dolphin through a local TCP port (ESPBAR_PORT).

Frames, both ways: u16 length (little endian, of what follows) | u8 type | u8 slot | payload.
Both ends open with HELLO (JSON): the ESP32 with the EspBar token, Dolphin with its session
id and the session hook token. Wolfy routes the Wii Remotes to the Dolphin whose session
belongs to the linked device, and asks the ESP32 to look for Wii Remotes only then.
"""
import asyncio
import hmac
import json
import struct
import time

from fastapi import WebSocket, WebSocketDisconnect

from . import espbar, settings, store, wolf_api

HELLO, WIIMOTE_ON, WIIMOTE_OFF, REPORT, DROP, PING, SCAN = range(1, 8)
SLOTS = 4


class Peer:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, info: dict):
        self.reader, self.writer, self.info = reader, writer, info
        self.since = time.strftime("%Y-%m-%d %H:%M:%S")

    def send(self, type_: int, slot: int = 0, payload: bytes = b"") -> None:
        if not self.writer.is_closing():
            self.writer.write(struct.pack("<HBB", len(payload) + 2, type_, slot) + payload)

    def close(self) -> None:
        self.writer.close()


_esp: Peer | None = None
_dolphins: dict[str, Peer] = {}   # session id -> Dolphin of that Wii session
_active: str | None = None        # session receiving the Wii Remotes
_wiimotes: dict[int, str] = {}    # slot -> Bluetooth address
_idle_since: float | None = None  # no session for the Wii Remotes since (monotonic)
IDLE_DROP = 30                     # then they are turned off (Dolphin quit without doing it)


class WsStream:
    """A WebSocket seen as a byte stream (reader + writer): frames may span messages."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.buf = bytearray()
        self.out: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=512)
        self.closing = False
        self.sender = asyncio.create_task(self._send_loop())

    async def readexactly(self, n: int) -> bytes:
        while len(self.buf) < n:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                raise ConnectionError("closed")
            self.buf += msg.get("bytes") or b""
        data = bytes(self.buf[:n])
        del self.buf[:n]
        return data

    async def _send_loop(self) -> None:
        try:
            while (data := await self.out.get()) is not None:
                await self.ws.send_bytes(data)
        except Exception:
            self.closing = True

    def write(self, data: bytes) -> None:
        try:
            self.out.put_nowait(data)
        except asyncio.QueueFull:
            pass  # the ESP32 is not keeping up: drop, the game sends more

    def is_closing(self) -> bool:
        return self.closing

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        try:
            self.out.put_nowait(None)  # the sender stops after what is queued
        except asyncio.QueueFull:
            self.sender.cancel()

    def get_extra_info(self, name: str, default=None):
        if name == "peername":  # behind SWAG: the real address is in X-Forwarded-For
            fwd = self.ws.headers.get("x-forwarded-for", "").split(",")[0].strip()
            return (fwd or (self.ws.client.host if self.ws.client else ""), 0)
        return default


async def _read_frame(reader: asyncio.StreamReader, timeout: float | None = None):
    head = await asyncio.wait_for(reader.readexactly(2), timeout)
    (n,) = struct.unpack("<H", head)
    if n < 2:
        raise ConnectionError("bad frame")
    body = await asyncio.wait_for(reader.readexactly(n), timeout)
    return body[0], body[1], body[2:]


def _bdaddr(raw: bytes) -> str:
    return ":".join(f"{b:02X}" for b in raw[:6])


async def _linked_sessions() -> set[str]:
    """Wolf sessions of the device the EspBar is linked to."""
    client = espbar.client_id()
    if not client:
        return set()
    try:
        sessions = (await wolf_api.get("sessions")).get("sessions", [])
    except Exception:
        return set()
    # a session is known by its session_id, or by its client_id (what Wolf's sessions/stop takes)
    return {str(s[k]) for s in sessions if str(s.get("client_id")) == client
            for k in ("session_id", "id", "client_id") if s.get(k) is not None}


async def linked(session: str) -> bool:
    return session in await _linked_sessions()


async def _route() -> None:
    """Give the Wii Remotes to the linked device's Dolphin (if it runs), tell the ESP32."""
    global _active
    sessions = await _linked_sessions() if _dolphins else set()
    target = next((s for s in _dolphins if s in sessions), None)
    if target != _active:
        if _active in _dolphins:
            for slot in _wiimotes:
                _dolphins[_active].send(WIIMOTE_OFF, slot)
        _active = target
        if target:
            for slot, addr in _wiimotes.items():
                _dolphins[target].send(WIIMOTE_ON, slot, bytes.fromhex(addr.replace(":", "")))
        if _esp:
            _esp.send(SCAN, 0, bytes([1 if target else 0]))
        print(f"EspBar: Wii Remotes -> {('session ' + target) if target else 'nobody'}", flush=True)


async def _serve_esp(peer: Peer) -> None:
    global _esp
    if _esp:
        _esp.close()
    _esp = peer
    _wiimotes.clear()
    peer.send(SCAN, 0, bytes([1 if _active else 0]))
    print(f"EspBar: ESP32 {peer.info.get('mac')} connected", flush=True)
    try:
        while True:
            type_, slot, payload = await _read_frame(peer.reader, 10)
            target = _dolphins.get(_active) if _active else None
            if type_ == REPORT:
                if target:
                    target.send(REPORT, slot, payload)
            elif type_ == WIIMOTE_ON and slot < SLOTS:
                _wiimotes[slot] = _bdaddr(payload)
                if target:
                    target.send(WIIMOTE_ON, slot, payload)
            elif type_ == WIIMOTE_OFF and slot < SLOTS:
                _wiimotes.pop(slot, None)
                if target:
                    target.send(WIIMOTE_OFF, slot)
    finally:
        if _esp is peer:
            _esp = None
            if _active in _dolphins:
                for slot in _wiimotes:
                    _dolphins[_active].send(WIIMOTE_OFF, slot)
            _wiimotes.clear()
            print("EspBar: ESP32 disconnected", flush=True)


async def _serve_dolphin(peer: Peer) -> None:
    session = str(peer.info.get("session") or "")
    if old := _dolphins.get(session):
        old.close()
    _dolphins[session] = peer
    await _route()
    try:
        while True:
            type_, slot, payload = await _read_frame(peer.reader)
            if _active == session and _esp and type_ in (REPORT, DROP):
                _esp.send(type_, slot, payload)
    finally:
        if _dolphins.get(session) is peer:
            del _dolphins[session]
            await _route()


async def serve_websocket(ws: WebSocket) -> None:
    """The ESP32 (Wolfy's /api/espbar/ws)."""
    await ws.accept()
    stream = WsStream(ws)
    try:
        await _handle(stream, stream, roles=("esp",))
    finally:
        stream.close()
        try:
            await ws.close()
        except Exception:
            pass


async def _handle(reader, writer, roles=("esp", "dolphin")) -> None:
    peer = None
    try:
        type_, _, payload = await _read_frame(reader, 5)
        info = json.loads(payload) if type_ == HELLO else {}
        if info.get("role") not in roles:
            return
        token = str(info.get("token", ""))
        if hasattr(writer, "transport"):
            writer.transport.set_write_buffer_limits(high=64 * 1024)
        if info.get("role") == "esp" and hmac.compare_digest(token, espbar.token()):
            info["ip"] = writer.get_extra_info("peername", ("", 0))[0]
            peer = Peer(reader, writer, info)
            await _serve_esp(peer)
        elif info.get("role") == "dolphin" and hmac.compare_digest(token, settings.hook_token()):
            peer = Peer(reader, writer, info)
            await _serve_dolphin(peer)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ValueError, OSError,
            WebSocketDisconnect):
        pass
    finally:
        writer.close()


async def _keepalive() -> None:
    """Ping both ends (they drop a silent link after 6 s), follow the link and the sessions,
    turn off Wii Remotes left without a session."""
    global _idle_since
    while True:
        await asyncio.sleep(2)
        for peer in [_esp, *_dolphins.values()]:
            if peer:
                peer.send(PING)
        try:
            await _route()
        except Exception as exc:
            print(f"EspBar: routing failed: {exc}", flush=True)
        if _active or not _wiimotes:
            _idle_since = None
        elif _idle_since is None:
            _idle_since = time.monotonic()
        elif time.monotonic() - _idle_since > IDLE_DROP and _esp:
            print("EspBar: no Wii session, turning the Wii Remotes off", flush=True)
            for slot in _wiimotes:
                _esp.send(DROP, slot)
            _idle_since = None


async def start() -> None:
    await asyncio.start_server(lambda r, w: _handle(r, w, roles=("dolphin",)), "0.0.0.0", settings.ESPBAR_PORT)
    asyncio.create_task(_keepalive())
    print(f"EspBar: relay listening on port {settings.ESPBAR_PORT}", flush=True)


def status() -> dict:
    names = store.get("clients")
    return {
        "online": _esp is not None,
        "esp": {k: _esp.info.get(k) for k in ("mac", "version", "ip")} | {"since": _esp.since} if _esp else None,
        "wiimotes": [{"slot": s + 1, "addr": a} for s, a in sorted(_wiimotes.items())],
        "session": _active,
        "client_name": names.get(espbar.client_id() or "", {}).get("name", "") if _active else "",
    }
