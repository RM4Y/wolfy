"""Releases on GitHub of the Switch emulator fork in use (emulator.version: EMU_REPO, EMU_BINARY),
and the version file itself. Standard library only: used by update-emulator.py and fetch-release.py
in images/switch, and by Wolfy (backend/wolfy/switch_update.py)."""
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION_FILE = HERE / "emulator.version"
KEYS = ("EMU_NAME", "EMU_REPO", "EMU_BINARY", "EMU_TAG", "EMU_DATE", "EMU_COMMIT", "EMU_LLVM", "EMU_QT")
# where the release workflows keep the Linux PGO toolchain (Lichii, Eglantine)
WORKFLOWS = ("release-binaries.yml", "build-linux.yml")


def _get(url: str, raw: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": "wolfy-switch-update",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    return data.decode() if raw else json.loads(data)


def read(path: Path = VERSION_FILE) -> dict:
    """KEY=value lines of a version file (missing file: {})."""
    out = {}
    try:
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in KEYS:
                out[key] = value.strip()
    except OSError:
        pass
    return out


def render(version: dict) -> str:
    comments = [line for line in VERSION_FILE.read_text().splitlines() if line.startswith("#")] \
        if VERSION_FILE.is_file() else []
    return "\n".join([*comments, *(f"{k}={version[k]}" for k in KEYS)]) + "\n"


def assets(binary: str) -> tuple[str, ...]:
    """The AppImage the image is built on: the PGO build first, else the plain one."""
    return (f"{binary}-linux-x86_64-pgo.AppImage", f"{binary}-linux-x86_64.AppImage")


def _asset(release: dict, binary: str) -> str | None:
    names = {a["name"] for a in release.get("assets", [])}
    return next((a for a in assets(binary) if a in names), None)


def _build_number(tag: str) -> int:
    m = re.fullmatch(r"build-(\d+)", tag or "")
    return int(m[1]) if m else -1


def latest(current: dict | None = None) -> dict:
    """Newest published release (no draft, no pre-release) with a Linux x86_64 AppImage."""
    current = current or read()
    repo, binary = current["EMU_REPO"], current["EMU_BINARY"]
    releases = [r for r in _get(f"https://api.github.com/repos/{repo}/releases?per_page=30")
                if not r["draft"] and not r["prerelease"] and _asset(r, binary)]
    if not releases:
        raise RuntimeError(f"aucune version Linux publiée trouvée pour {repo}")
    r = max(releases, key=lambda r: (r["published_at"], _build_number(r["tag_name"])))
    return {"tag": r["tag_name"], "title": r.get("name") or r["tag_name"],
            "published": r["published_at"], "url": r["html_url"]}


def version_for(tag: str, current: dict | None = None, published: str = "") -> dict:
    """The version file of a release of the current fork: its commit, its date and the toolchain
    of its Linux PGO build (kept from the current version when its workflow can't be read)."""
    current = current or read()
    repo = current["EMU_REPO"]
    commit = _get(f"https://api.github.com/repos/{repo}/commits/{tag}")["sha"]
    if not published:
        published = _get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")["published_at"]
    llvm, qt = current.get("EMU_LLVM", "23"), current.get("EMU_QT", "6.8.3")
    for wf_name in WORKFLOWS:
        try:
            wf = _get(f"https://raw.githubusercontent.com/{repo}/{commit}/.github/workflows/{wf_name}", raw=True)
        except OSError:
            continue
        if m := re.search(r'PGO_LLVM_VERSION:\s*"?(\d+)', wf):
            llvm = m[1]
        if m := re.search(r'version:\s*"(6\.\d+\.\d+)"', wf):
            qt = m[1]
        break
    return {**{k: current[k] for k in ("EMU_NAME", "EMU_REPO", "EMU_BINARY")},
            "EMU_TAG": tag, "EMU_DATE": published, "EMU_COMMIT": commit, "EMU_LLVM": llvm, "EMU_QT": qt}


def newer(latest_release: dict, current: dict) -> bool:
    """A release published after the installed one (tags like v0.1.0-rc3 don't sort)."""
    return (latest_release["tag"] != current.get("EMU_TAG")
            and latest_release["published"] > current.get("EMU_DATE", ""))
