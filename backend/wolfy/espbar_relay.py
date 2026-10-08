"""EspBar relay between the ESP32 boards (Wii Remotes over Bluetooth) and the Dolphin of the Wii
session of each one's device (images/dolphin/espbar/IOEspBar.cpp). An ESP32 comes through a WebSocket
on Wolfy's own address (/api/espbar/ws: wss://wolfy.rm4.fr through SWAG, or ws://<lan ip>:8420),
the sessions' Dolphin through a local TCP port (ESPBAR_PORT).

Frames, both ways: u16 length (little endian, of what follows) | u8 type | u8 slot | payload.
Both ends open with HELLO (JSON): the ESP32 with the EspBar token and its id (base MAC: its
name and device, espbar.boards()), Dolphin with its session id and the session hook token.
Wolfy routes each EspBar's Wii Remotes to the Dolphin whose session belongs to its device, and
asks the ESP32 to look for Wii Remotes only then.
"""
import asyncio
import hmac
import json
import struct
import time

from fastapi import WebSocket, WebSocketDisconnect

from . import espbar, settings, wolf_api

HELLO, WIIMOTE_ON, WIIMOTE_OFF, REPORT, DROP, PING, SCAN, STATS = range(1, 9)
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


class Esp:
    """A connected EspBar, and where its Wii Remotes go."""

    def __init__(self, key: str, peer: Peer):
        self.key, self.peer = key, peer
        self.wiimotes: dict[int, str] = {}         # slot -> Bluetooth address
        self.traffic: dict[int, list[int]] = {}    # slot -> [reports to Dolphin, reports to the Wii Remote]
        self.active: str | None = None             # session receiving the Wii Remotes
        self.idle_since: float | None = None       # no session for the Wii Remotes since (monotonic)
        self.last_session: str | None = None       # last session that had the Wii Remotes
        self.flow = ""                             # last report flow sent by the ESP32 (STATS, every 2 s)

    @property
    def name(self) -> str:
        return espbar.board_name(self.key)

    def target(self) -> Peer | None:
        return _dolphins.get(self.active) if self.active else None

    def give(self, session: str | None) -> None:
        """Move the Wii Remotes to the Dolphin of <session> (or nobody), tell the ESP32."""
        if old := self.target():
            for slot in self.wiimotes:
                old.send(WIIMOTE_OFF, slot)
        self.active = session
        if new := self.target():
            self.last_session = session
            for slot, addr in self.wiimotes.items():
                new.send(WIIMOTE_ON, slot, bytes.fromhex(addr.replace(":", "")))
        self.peer.send(SCAN, 0, bytes([1 if session else 0]))
        print(f"{self.name}: Wii Remotes -> {('session ' + session) if session else 'nobody'}", flush=True)


_esps: dict[str, Esp] = {}        # board key -> connected EspBar
_dolphins: dict[str, Peer] = {}   # session id -> Dolphin of that Wii session
IDLE_DROP = 30                     # then they are turned off (Dolphin quit without doing it)
                                   # (at once when that session has ended)


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


async def _wolf_sessions(strict: bool = False) -> list[dict]:
    """Wolf's sessions (strict: Wolf unreachable raises)."""
    try:
        return (await wolf_api.get("sessions")).get("sessions", [])
    except Exception:
        if strict:
            raise
        return []


def _sessions_of(client: str | None, sessions: list[dict]) -> set[str]:
    # a session is known by its session_id, or by its client_id (what Wolf's sessions/stop takes)
    return {str(s[k]) for s in sessions if client and str(s.get("client_id")) == client
            for k in ("session_id", "id", "client_id") if s.get(k) is not None}


def _client_of(key: str) -> str | None:
    return espbar.boards().get(key, {}).get("client_id")


async def linked(session: str) -> bool:
    """The session belongs to a device that has an EspBar."""
    clients = {b["client_id"] for b in espbar.boards().values() if b.get("client_id")}
    if not clients:
        return False
    sessions = await _wolf_sessions()
    return any(session in _sessions_of(c, sessions) for c in clients)


async def _route() -> None:
    """Give each EspBar's Wii Remotes to its device's Dolphin (if it runs)."""
    if not _esps:
        return
    sessions = await _wolf_sessions() if _dolphins else []
    for esp in list(_esps.values()):
        mine = _sessions_of(_client_of(esp.key), sessions)
        target = next((s for s in _dolphins if s in mine), None)
        if target != esp.active:
            esp.give(target)


async def _serve_esp(peer: Peer) -> None:
    key = str(peer.info.get("id") or peer.info.get("mac") or "").lower()  # firmware < 10: no id
    if not key:
        return
    espbar.register(key)
    if old := _esps.get(key):
        old.peer.close()
    esp = _esps[key] = Esp(key, peer)
    peer.send(SCAN, 0, b"\0")
    print(f"{esp.name}: ESP32 {key} connected", flush=True)
    await _route()
    try:
        while True:
            type_, slot, payload = await _read_frame(peer.reader, 10)
            target = esp.target()
            if type_ == REPORT:
                if target:
                    target.send(REPORT, slot, payload)
                    if slot in esp.traffic:
                        esp.traffic[slot][0] += 1
            elif type_ == STATS:  # report flow of the ESP32, shown in Wolfy > Wii > EspBar
                esp.flow = payload.decode(errors="replace")
            elif type_ == WIIMOTE_ON and slot < SLOTS:
                esp.wiimotes[slot] = _bdaddr(payload)
                esp.traffic[slot] = [0, 0]
                print(f"{esp.name}: Wii Remote {esp.wiimotes[slot]} on slot {slot + 1} -> "
                      f"{('session ' + esp.active) if target else 'nobody'}", flush=True)
                if target:
                    target.send(WIIMOTE_ON, slot, payload)
            elif type_ == WIIMOTE_OFF and slot < SLOTS:
                up, down = esp.traffic.pop(slot, [0, 0])
                print(f"{esp.name}: Wii Remote {esp.wiimotes.pop(slot, '?')} of slot {slot + 1} gone "
                      f"({up} reports to Dolphin, {down} to the Wii Remote)", flush=True)
                if target:
                    target.send(WIIMOTE_OFF, slot)
    finally:
        if _esps.get(key) is esp:
            del _esps[key]
            if target := esp.target():
                for slot in esp.wiimotes:
                    target.send(WIIMOTE_OFF, slot)
            print(f"{esp.name}: ESP32 disconnected", flush=True)


async def _serve_dolphin(peer: Peer) -> None:
    session = str(peer.info.get("session") or "")
    if old := _dolphins.get(session):
        old.close()
    _dolphins[session] = peer
    print(f"EspBar: Dolphin of session {session} connected", flush=True)
    await _route()
    try:
        while True:
            type_, slot, payload = await _read_frame(peer.reader)
            esp = next((e for e in _esps.values() if e.active == session), None)
            if esp and type_ in (REPORT, DROP):
                esp.peer.send(type_, slot, payload)
                if type_ == REPORT and slot in esp.traffic:
                    esp.traffic[slot][1] += 1
            if type_ == DROP:
                print(f"EspBar: Dolphin of session {session} turns off the Wii Remote of slot {slot + 1}"
                      f"{f' of {esp.name}' if esp else ' (ignored: no EspBar for it)'}", flush=True)
    finally:
        if _dolphins.get(session) is peer:
            del _dolphins[session]
            print(f"EspBar: Dolphin of session {session} disconnected", flush=True)
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
    """Ping both ends (they drop a silent link after 6 s), follow the links and the sessions,
    turn off Wii Remotes left without a session."""
    while True:
        await asyncio.sleep(2)
        for peer in [*(e.peer for e in _esps.values()), *_dolphins.values()]:
            peer.send(PING)
        try:
            await _route()
        except Exception as exc:
            print(f"EspBar: routing failed: {exc}", flush=True)
        for esp in list(_esps.values()):
            if esp.active or not esp.wiimotes:
                esp.idle_since = None
                continue
            if esp.idle_since is None:
                esp.idle_since = time.monotonic()
            # Dolphin gone: its session ended (Moonlight quit), or Dolphin is restarting inside it
            # (dolphin-run.sh) and the Wii Remotes stay on for a while
            try:
                ended = bool(esp.last_session) and esp.last_session not in _sessions_of(
                    _client_of(esp.key), await _wolf_sessions(strict=True))
            except Exception:
                ended = False
            if ended or time.monotonic() - esp.idle_since > IDLE_DROP:
                print(f"{esp.name}: {'session ' + str(esp.last_session) + ' ended' if ended else 'no Wii session'}, "
                      "turning the Wii Remotes off", flush=True)
                for slot in esp.wiimotes:
                    esp.peer.send(DROP, slot)
                esp.idle_since = None
                esp.last_session = None


async def start() -> None:
    await asyncio.start_server(lambda r, w: _handle(r, w, roles=("dolphin",)), "0.0.0.0", settings.ESPBAR_PORT)
    asyncio.create_task(_keepalive())
    print(f"EspBar: relay listening on port {settings.ESPBAR_PORT}", flush=True)


def status() -> dict[str, dict]:
    """Connected EspBars, by board key."""
    return {key: {
        "esp": {k: esp.peer.info.get(k) for k in ("mac", "version", "ip", "boards")} | {"since": esp.peer.since},
        "wiimotes": [{"slot": s + 1, "addr": a} for s, a in sorted(esp.wiimotes.items())],
        "session": esp.active,
        "flow": esp.flow,
    } for key, esp in _esps.items()}
