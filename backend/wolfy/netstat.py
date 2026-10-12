"""Bandwidth of the Moonlight streams, per client IP: run on the host network with CAP_NET_RAW
(compose service wolfy-net), writes $WOLFY_NETSTAT every second for Wolfy.

Wolf gives no traffic figures; this counts what it sends: RTP video from UDP port 48100 and audio
from 48200 (Wolf's defaults). A classic BPF filter in the kernel keeps only those packets (the
host also carries torrents, Jellyfin...), truncated to their headers.

    python -m wolfy.netstat
"""
import ctypes
import json
import os
import socket
import struct
import time
from pathlib import Path

VIDEO_PORT = int(os.environ.get("WOLF_VIDEO_PORT", "48100"))
AUDIO_PORT = int(os.environ.get("WOLF_AUDIO_PORT", "48200"))
OUT = Path(os.environ.get("WOLFY_NETSTAT", "/net/netstat.json"))
HISTORY = 60  # seconds kept per client
ETH_P_ALL = 0x0003  # sent packets only reach ETH_P_ALL taps, not ETH_P_IP ones
PACKET_OUTGOING = 4
SO_ATTACH_FILTER = 26
SKF_AD_PROTOCOL = 0xFFFFF000

# SOCK_DGRAM packet socket: offsets start at the network header
# 0 ld protocol; 1 jeq IPv4 else drop; 2 ldb [9]; 3 jeq #17 (UDP) else drop; 4 ldh [6];
# 5 jset #0x1fff (fragment) drop; 6 ldxb 4*([0]&0xf); 7 ldh [x+0] (source port);
# 8 jeq video accept; 9 jeq audio accept else drop
FILTER = [
    (0x28, 0, 0, SKF_AD_PROTOCOL),
    (0x15, 0, 9, 0x0800),
    (0x30, 0, 0, 9),
    (0x15, 0, 7, 17),
    (0x28, 0, 0, 6),
    (0x45, 5, 0, 0x1FFF),
    (0xB1, 0, 0, 0),
    (0x48, 0, 0, 0),
    (0x15, 1, 0, VIDEO_PORT),
    (0x15, 0, 1, AUDIO_PORT),
    (0x06, 0, 0, 64),  # accept, 64 bytes are enough for the headers
    (0x06, 0, 0, 0),   # drop
]


def _socket() -> socket.socket:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETH_P_ALL))
    prog = ctypes.create_string_buffer(b"".join(struct.pack("HBBI", *i) for i in FILTER))
    fprog = struct.pack("HL", len(FILTER), ctypes.addressof(prog))  # struct sock_fprog
    s.setsockopt(socket.SOL_SOCKET, SO_ATTACH_FILTER, fprog)  # the kernel copies the program
    s.settimeout(0.25)
    return s


def main() -> None:
    sock = _socket()
    clients: dict[str, dict] = {}  # ip -> {video, audio (bytes this second), history, last}
    tick = time.monotonic()
    while True:
        try:
            pkt, addr = sock.recvfrom(64)
            ifname, pkttype = addr[0], addr[2]
            if pkttype == PACKET_OUTGOING and ifname != "lo" and len(pkt) >= 20:
                total = struct.unpack_from("!H", pkt, 2)[0]  # IP total length (pkt is truncated)
                ihl = (pkt[0] & 0x0F) * 4
                sport = struct.unpack_from("!H", pkt, ihl)[0] if len(pkt) >= ihl + 2 else 0
                dst = socket.inet_ntoa(pkt[16:20])
                c = clients.setdefault(dst, {"video": 0, "audio": 0, "history": [], "last": 0.0})
                c["video" if sport == VIDEO_PORT else "audio"] += total
        except socket.timeout:
            pass
        now = time.monotonic()
        if now - tick >= 1:
            span, tick = now - tick, now
            _flush(clients, span)


def _flush(clients: dict, span: float) -> None:
    out = {}
    for ip, c in list(clients.items()):
        video, audio = c["video"] * 8 / span, c["audio"] * 8 / span  # bit/s
        c["video"] = c["audio"] = 0
        if video or audio:
            c["last"] = time.time()
        c["history"] = (c["history"] + [round(video + audio)])[-HISTORY:]
        if not any(c["history"]):  # silent for a minute: forgotten
            del clients[ip]
            continue
        out[ip] = {"video_bps": round(video), "audio_bps": round(audio), "history": c["history"],
                   "last_packet": c["last"]}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"time": time.time(), "clients": out}))
    tmp.replace(OUT)


if __name__ == "__main__":
    main()
