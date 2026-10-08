#!/usr/bin/env python3
"""Motion pointer on the right stick, for the Switch games that aim with the gyroscope in TV
mode (Captain Toad: point with the Joy-Con, ZR to select). The Wolf pad is an Xbox pad,
without gyroscope.

L3 + R3 (pressed then released) toggles the pointer mode of that pad: the right stick then
turns the controller (gyroscope), the game's pointer follows it, and the game sees the
right stick at rest (no camera move). L3 + R3 again gives the stick back to the game.

Eden reads the motion and the right stick from this DSU ("cemuhook") server on
127.0.0.1:26760, pad n = the n-th Wolf pad of the session (startup-app.sh binds players
1-4's motion and right stick to it; the rest of the pad stays on SDL).
"""
import fcntl
import os
import re
import select
import socket
import struct
import sys
import time
import zlib

PORT = 26760
BTN_THUMBL, BTN_THUMBR = 317, 318
ABS_RX, ABS_RY = 3, 4
EV_KEY, EV_ABS = 1, 3
EVENT = struct.Struct("llHHi")
SPEED = 120.0   # deg/s (DSU units), stick fully pushed; halfway: a quarter (fine aiming)
DEADZONE = 0.12
RATE = 1 / 125  # pad data sent to Eden
CLIENT_TIMEOUT = 6  # Eden asks again every 3 s

SERVER_ID = int.from_bytes(os.urandom(4), "little")
VERSION, PORT_INFO, PAD_DATA = 0x100000, 0x100001, 0x100002


def log(msg):
    print(f"[stick-gyro] {msg}", flush=True)


def gamepads() -> list[str]:
    """Event nodes of the session's pads, in the order Eden numbers them (creation order)."""
    try:
        text = open("/proc/bus/input/devices").read()
    except OSError:
        return []
    nodes = []
    for block in text.split("\n\n"):
        m = re.search(r"H: Handlers=(.*)", block)
        if m and re.search(r"\bjs\d+", m.group(1)):
            ev = re.search(r"\bevent(\d+)", m.group(1))
            if ev and os.path.exists(f"/dev/input/event{ev.group(1)}"):
                nodes.append(int(ev.group(1)))
    return [f"/dev/input/event{n}" for n in sorted(nodes)]


class Pad:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.held = set()
        self.combo = False
        self.pointer = False
        self.axes = {ABS_RX: 0.0, ABS_RY: 0.0}  # -1..1, deadzone applied (pointer)
        self.raw = {ABS_RX: 0.0, ABS_RY: 0.0}   # -1..1 (forwarded to the game)
        self.ranges = {}
        for code in self.axes:
            buf = bytearray(24)  # struct input_absinfo
            try:
                fcntl.ioctl(self.fd, 0x80184540 + code, buf)  # EVIOCGABS(code)
                _, lo, hi = struct.unpack_from("iii", buf)
            except OSError:
                lo, hi = -32768, 32767
            self.ranges[code] = (lo, hi)

    def read(self) -> bool:
        try:
            data = os.read(self.fd, EVENT.size * 64)
        except BlockingIOError:
            return True
        except OSError:
            return False
        for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _, _, typ, code, value = EVENT.unpack_from(data, i)
            if typ == EV_ABS and code in self.axes:
                lo, hi = self.ranges[code]
                v = max(-1.0, min(1.0, (value - (lo + hi) / 2) / ((hi - lo) / 2 or 1)))
                self.raw[code] = v
                self.axes[code] = 0.0 if abs(v) < DEADZONE else max(-1.0, min(1.0, v))
            elif typ == EV_KEY and code in (BTN_THUMBL, BTN_THUMBR) and value in (0, 1):
                (self.held.add if value else self.held.discard)(code)
                if len(self.held) == 2:
                    self.combo = True
                elif self.combo and not self.held:  # toggled once both are released
                    self.combo = False
                    self.pointer = not self.pointer
                    log(f"{self.path}: pointer {'on' if self.pointer else 'off'}")
        return True

    def gyro(self) -> tuple[float, float]:
        """(pitch, yaw) in deg/s: stick up = pointer up, stick right = pointer right."""
        if not self.pointer:
            return 0.0, 0.0
        x, y = self.axes[ABS_RX], self.axes[ABS_RY]
        mag = min(1.0, (x * x + y * y) ** 0.5)
        return -y * mag * SPEED, x * mag * SPEED

    def stick(self) -> tuple[int, int]:
        """Right stick for the game, DSU bytes (127 = centre, same directions as SDL)."""
        if self.pointer:
            return 127, 127
        return tuple(round(127 + self.raw[c] * 127) for c in (ABS_RX, ABS_RY))

    def close(self):
        os.close(self.fd)


def message(kind: int, payload: bytes) -> bytes:
    header = struct.pack("<4sHHII", b"DSUS", 1001, len(payload) + 4, 0, SERVER_ID)
    body = struct.pack("<I", kind) + payload
    crc = zlib.crc32(header + body)
    return header[:8] + struct.pack("<I", crc) + header[12:] + body


def port_info(slot: int) -> bytes:
    # slot, connected, full gyro, USB, MAC, battery full, active
    return struct.pack("<BBBB6sBB", slot, 2, 2, 1, bytes([0, 0, 0, 0, 0, slot + 1]), 5, 1)


def pad_data(slot: int, counter: int, pitch: float, yaw: float, rx: int, ry: int) -> bytes:
    return (port_info(slot) + struct.pack("<IHBB4B12x12x", counter, 0, 0, 0, 127, 127, rx, ry)
            + struct.pack("<Q3f3f", int(time.monotonic() * 1e6), 0.0, 0.0, 0.0, pitch, yaw, 0.0))


def main() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", PORT))
    sock.setblocking(False)
    log(f"DSU server on 127.0.0.1:{PORT}, L3 + R3 toggles the right stick pointer")
    pads: dict[str, Pad] = {}
    clients: dict[tuple, float] = {}
    counter, last_scan, last_send = 0, 0.0, 0.0
    while True:
        now = time.monotonic()
        if now - last_scan > 2:
            last_scan = now
            wanted = gamepads()
            for path in [p for p in pads if p not in wanted]:
                pads.pop(path).close()
            for path in wanted:
                if path not in pads:
                    try:
                        pads[path] = Pad(path)
                    except OSError as exc:
                        log(f"cannot open {path}: {exc}")
            order = [p for p in wanted if p in pads]
        by_fd = {p.fd: p for p in pads.values()}
        ready, _, _ = select.select([sock, *by_fd], [], [], max(0.0, last_send + RATE - now))
        for fd in ready:
            if fd is sock:
                try:
                    data, addr = sock.recvfrom(128)
                except OSError:
                    continue
                if len(data) < 20 or data[:4] != b"DSUC":
                    continue
                kind = struct.unpack_from("<I", data, 16)[0]
                if kind == VERSION:
                    sock.sendto(message(VERSION, struct.pack("<H", 1001)), addr)
                elif kind == PORT_INFO and len(data) >= 24:
                    count = min(4, struct.unpack_from("<I", data, 20)[0])
                    for slot in data[24:24 + count]:
                        if slot < 4:
                            sock.sendto(message(PORT_INFO, port_info(slot)), addr)
                elif kind == PAD_DATA:
                    if addr not in clients:
                        log(f"Eden connected from {addr[0]}:{addr[1]}")
                    clients[addr] = now
            elif not by_fd[fd].read():
                pads.pop(by_fd[fd].path).close()
        now = time.monotonic()
        if now - last_send >= RATE:
            last_send = now
            for addr in [a for a, t in clients.items() if now - t > CLIENT_TIMEOUT]:
                clients.pop(addr)
            if clients:
                counter = (counter + 1) & 0xFFFFFFFF
                for slot in range(4):
                    pad = pads.get(order[slot]) if slot < len(order) else None
                    pitch, yaw = pad.gyro() if pad else (0.0, 0.0)
                    rx, ry = pad.stick() if pad else (127, 127)
                    packet = message(PAD_DATA, pad_data(slot, counter, pitch, yaw, rx, ry))
                    for addr in clients:
                        sock.sendto(packet, addr)


if __name__ == "__main__":
    sys.exit(main())
