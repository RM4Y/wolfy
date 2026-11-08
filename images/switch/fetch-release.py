#!/usr/bin/env python3
"""Downloads the Linux AppImage of a release of the Switch emulator fork and extracts it without
running it.

    fetch-release.py <emulator.version> <dest>

AppImages can't mount in a container (no FUSE), and running one to extract it would
execute its runtime: the squashfs image is read directly instead, right after the ELF
runtime (offset = end of the section header table).
"""
import struct
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from emu_release import assets, read


def main(version_file: str, dest: str) -> None:
    v = read(Path(version_file))
    repo, tag = v["EMU_REPO"], v["EMU_TAG"]
    path = "/tmp/emulator.AppImage"
    for asset in assets(v["EMU_BINARY"]):
        url = f"https://github.com/{repo}/releases/download/{tag}/{asset}"
        req = urllib.request.Request(url, headers={"User-Agent": "wolfy-switch"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
                print(f"{v['EMU_NAME']} {tag} : {url}", flush=True)
                f.write(r.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    else:
        sys.exit(f"pas d'AppImage Linux x86_64 dans {repo} {tag}")

    with open(path, "rb") as f:
        head = f.read(64)
        if head[:4] != b"\x7fELF":
            sys.exit("pas un exécutable ELF")
        shoff, = struct.unpack_from("<Q", head, 0x28)
        shentsize, shnum = struct.unpack_from("<HH", head, 0x3A)
        offset = shoff + shentsize * shnum
        f.seek(offset)
        if f.read(4) != b"hsqs":
            sys.exit(f"pas de squashfs à l'offset {offset}")
    subprocess.run(["unsquashfs", "-q", "-n", "-o", str(offset), "-d", dest, path], check=True)
    with open(f"{dest}/VERSION", "w") as f:
        f.write(f"{v['EMU_NAME']} {tag}\n")
    Path(path).unlink()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
