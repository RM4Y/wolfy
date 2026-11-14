"""Updates of the other apps' images (Wii / GameCube, PlayStation, Steam), like the app Switch's
(switch_update.py): what each image holds (read from the image itself), the newest versions
(GitHub, the libretro buildbot, the Games on Whales registry), and the update job: the image built
again with the new versions as build args (they also invalidate Docker's cache from that step on).

Components of an image:
  base     its Games on Whales base image: newer on the registry, or the image not built on the
           local copy (pulled by another build) -> rebuild (build_steps pulls it)
  core     a libretro core of the buildbot (Last-Modified of its zip)
  rpcs3    RPCS3's newest Linux AppImage (pinned: RPCS3_URL)
  vita3k   Vita3K's "continuous" release (its date)
  dolphin  the Better Wii Menu DE fork's newest commit (pinned: ARG REF of the Dockerfile,
           rewritten once the new version is built, like images/switch/emulator.version)
A failed build leaves the installed image as it was (its tag only moves at the end)."""
import io
import json
import re
import tarfile
import threading
import time
import urllib.request
from email.utils import parsedate_to_datetime

from fastapi import HTTPException

from . import docker_ops, emulators, settings

CHECK_EVERY = 15 * 60  # GitHub allows 60 unauthenticated requests an hour
BUILDBOT = "https://buildbot.libretro.com/nightly/linux/x86_64/latest"
DOLPHIN_REPO = "Gavin-S-Dev/Better-Wii-Menu-DE"
RA_CORES = {"mednafen_psx_hw": "Beetle PSX HW (PS1)", "pcsx2": "LRPS2 (PS2)", "ppsspp": "PPSSPP (PSP)"}

# per emulator: its components, in display order
SOURCES = {
    "retroarch": [{"kind": "base", "key": "base", "name": "RetroArch (image Games on Whales)",
                   "ref": "ghcr.io/games-on-whales/retroarch:edge"},
                  *({"kind": "core", "key": c, "name": n} for c, n in RA_CORES.items()),
                  {"kind": "rpcs3", "key": "rpcs3", "name": "RPCS3 (PS3)"},
                  {"kind": "vita3k", "key": "vita3k", "name": "Vita3K (PS Vita)"}],
    "dolphin": [{"kind": "dolphin", "key": "dolphin", "name": "Dolphin Better Wii Menu DE"},
                {"kind": "base", "key": "base", "name": "Base Games on Whales",
                 "ref": "ghcr.io/games-on-whales/base-app:edge"}],
    "steam": [{"kind": "base", "key": "base", "name": "Steam (image Games on Whales)",
               "ref": "ghcr.io/games-on-whales/steam:edge"}],
}

_lock = threading.Lock()
_checked: dict[str, dict] = {}     # emulator id -> {"at", "error", key -> latest}
_installed: dict[str, dict] = {}  # image id -> files read from it
_jobs: dict[str, str] = {}        # emulator id -> job id


def supported(emu_id: str) -> bool:
    return emu_id in SOURCES


def _emu(emu_id: str) -> dict:
    if emu_id not in SOURCES:
        raise HTTPException(404, "Pas de mise à jour suivie pour cet émulateur")
    return emulators.BY_ID[emu_id]


def _get(url: str, head: bool = False):
    req = urllib.request.Request(url, method="HEAD" if head else "GET",
                                 headers={"User-Agent": "wolfy-image-update", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.headers if head else json.loads(r.read())


def _job(emu_id: str):
    job = docker_ops.JOBS.get(_jobs.get(emu_id, ""))
    return job if job and job.status == "running" else None


# ------------------------------------------------------------------- what the image holds

def _image_files(ref: str, paths: list[str]) -> dict:
    """Text files of an image (no container run: created, copied out, removed), by image id."""
    api = docker_ops.client().api
    image_id = api.inspect_image(ref)["Id"]
    if image_id in _installed:
        return _installed[image_id]
    out = {}
    container = api.create_container(ref, entrypoint=["true"])
    try:
        for path in paths:
            try:
                stream, _ = api.get_archive(container["Id"], path)
                with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
                    member = tar.next()
                    out[path] = tar.extractfile(member).read().decode(errors="replace") if member else ""
            except Exception:  # file absent (image built before it was written)
                out[path] = None
    finally:
        api.remove_container(container["Id"], force=True)
    _installed[image_id] = out
    return out


def _versions_file(text: str | None) -> dict:
    """/opt/wolfy/cores/VERSIONS of the PlayStation image: "<name>  <version>[  <url>]" lines."""
    out = {}
    for line in (text or "").splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 2:
            out[parts[0].removesuffix("_libretro.so")] = parts[1:]
    return out


def _base_state(ref: str, image: str) -> dict:
    """The base image: local copy, whether IMAGE was built on it, whether the registry has newer."""
    api = docker_ops.client().api
    try:
        base = api.inspect_image(ref)
    except Exception:
        return {"installed": "?", "built_on_local": False, "local_digests": []}
    try:
        layers = api.inspect_image(image)["RootFS"]["Layers"]
    except Exception:
        layers = []
    base_layers = base["RootFS"]["Layers"]
    built_on_local = layers[:len(base_layers)] == base_layers
    local = f"image du {(base.get('Created') or '')[:10]}"
    return {"installed": local if built_on_local else "image plus ancienne", "local": local,
            "built_on_local": built_on_local,
            "local_digests": [d.split("@", 1)[1] for d in base.get("RepoDigests", [])]}


def installed(emu_id: str) -> dict:
    """key -> {"version": text shown, "value": what is compared / pinned}"""
    emu = _emu(emu_id)
    if not docker_ops.image_info(emu["image"]).get("present"):
        return {}
    out = {}
    if emu_id == "retroarch":
        files = _image_files(emu["image"], ["/opt/wolfy/cores/VERSIONS"])
        versions = _versions_file(files["/opt/wolfy/cores/VERSIONS"])
        for c in RA_CORES:
            if c in versions:
                out[c] = {"version": _day(versions[c][0]), "value": versions[c][0]}
        if "rpcs3" in versions:
            asset = versions["rpcs3"][0]
            out["rpcs3"] = {"version": _rpcs3_version(asset), "value": asset,
                            "url": versions["rpcs3"][1] if len(versions["rpcs3"]) > 1 else ""}
        if "vita3k" in versions:
            out["vita3k"] = {"version": _day(versions["vita3k"][0]), "value": versions["vita3k"][0]}
    if emu_id == "dolphin":
        files = _image_files(emu["image"], ["/opt/dolphin/VERSION", "/opt/dolphin/COMMIT"])
        commit = (files["/opt/dolphin/COMMIT"] or "").strip()
        if not commit:  # image built before COMMIT: "git describe" (<hash>, or v1.0-2-g<hash>)
            m = re.search(r"(?:^|-g)([0-9a-f]{7,40})$", (files["/opt/dolphin/VERSION"] or "").strip())
            commit = m[1] if m else ""
        if commit:
            out["dolphin"] = {"version": commit[:10], "value": commit}
    for src in SOURCES[emu_id]:
        if src["kind"] == "base":
            state = _base_state(src["ref"], emu["image"])
            out[src["key"]] = {"version": state["installed"], "value": state}
    return out


def _day(value: str) -> str:
    """A date (HTTP or ISO) as YYYY-MM-DD HH:MM."""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return value[:16].replace("T", " ")


def _rpcs3_version(asset: str) -> str:
    m = re.search(r"rpcs3-(v[\d.]+-\d+)", asset)
    return m[1] if m else asset


# ------------------------------------------------------------------- newest versions

def _latest_of(src: dict) -> dict:
    kind = src["kind"]
    if kind == "base":
        digest = docker_ops.client().api.inspect_distribution(src["ref"])["Descriptor"]["digest"]
        return {"version": "nouvelle image publiée", "value": digest}
    if kind == "core":
        date = _get(f"{BUILDBOT}/{src['key']}_libretro.so.zip", head=True)["Last-Modified"]
        return {"version": _day(date), "value": date}
    if kind == "rpcs3":
        rel = _get("https://api.github.com/repos/RPCS3/rpcs3-binaries-linux/releases/latest")
        asset = next(a for a in rel["assets"] if a["name"].endswith(".AppImage"))
        return {"version": _rpcs3_version(asset["name"]), "value": asset["name"],
                "url": asset["browser_download_url"], "page": rel["html_url"]}
    if kind == "vita3k":
        rel = _get("https://api.github.com/repos/Vita3K/Vita3K/releases/tags/continuous")
        return {"version": _day(rel["published_at"]), "value": rel["published_at"], "page": rel["html_url"]}
    if kind == "dolphin":
        commit = _get(f"https://api.github.com/repos/{DOLPHIN_REPO}/commits?per_page=1")[0]
        return {"version": f"{commit['sha'][:10]} ({commit['commit']['committer']['date'][:10]})",
                "value": commit["sha"], "page": commit["html_url"]}
    raise ValueError(kind)


def _is_newer(src: dict, inst: dict | None, new: dict | None) -> bool:
    if not new:
        return False
    if not inst:
        return True  # unknown (image built before Wolfy recorded it): rebuilding gets the newest
    kind, have, want = src["kind"], inst["value"], new["value"]
    if kind == "base":
        return want not in have["local_digests"] or not have["built_on_local"]
    if kind == "core":
        try:
            return parsedate_to_datetime(want) > parsedate_to_datetime(have)
        except (TypeError, ValueError):
            return want != have
    if kind == "vita3k":
        return want > have
    if kind == "dolphin":
        return not want.startswith(have)
    return want != have


def _latest(emu_id: str, refresh: bool) -> dict:
    with _lock:
        cached = _checked.get(emu_id)
        if not refresh and cached and time.time() - cached["at"] < CHECK_EVERY:
            return cached
        out, errors = {"at": time.time()}, []
        for src in SOURCES[emu_id]:
            try:
                out[src["key"]] = _latest_of(src)
            except Exception as exc:  # offline, rate limit: shown, retried at the next check
                errors.append(f"{src['name']} : {exc}")
                if cached and src["key"] in cached:
                    out[src["key"]] = cached[src["key"]]
        out["error"] = " · ".join(errors) or None
        _checked[emu_id] = out
        return out


def status(emu_id: str, refresh: bool = False) -> dict:
    emu = _emu(emu_id)
    latest = _latest(emu_id, refresh)
    inst = installed(emu_id)
    components = []
    for src in SOURCES[emu_id]:
        have, new = inst.get(src["key"]), latest.get(src["key"])
        newest = new["version"] if new else None
        if src["kind"] == "base" and new and have and new["value"] in have["value"]["local_digests"]:
            newest = have["value"]["local"]  # already downloaded (by another image's build)
        components.append({"key": src["key"], "name": src["name"],
                           "installed": have["version"] if have else None,
                           "latest": newest,
                           "url": (new or {}).get("page"),
                           "update": _is_newer(src, have, new)})
    job = _job(emu_id)
    present = docker_ops.image_info(emu["image"]).get("present")
    return {"components": components, "checked": latest["at"], "error": latest["error"],
            "update_available": bool(present) and any(c["update"] for c in components),
            "job": job.as_dict() if job else None}


# ------------------------------------------------------------------- update job

def _rpcs3_args(v: dict) -> dict:
    return {"RPCS3_URL": v["url"]} if v.get("url") else {}


def build_args(emu_id: str, versions: dict) -> dict:
    """Build args pinning VERSIONS (key -> {"value", ...}) in the image of EMU_ID."""
    args = {}
    if emu_id == "retroarch":
        if all(c in versions for c in RA_CORES):
            args["CORES_STAMP"] = " ".join(versions[c]["value"] for c in RA_CORES)
        if "rpcs3" in versions:
            args.update(_rpcs3_args(versions["rpcs3"]))
        if "vita3k" in versions:
            args["VITA3K_STAMP"] = versions["vita3k"]["value"]
    if emu_id == "dolphin" and "dolphin" in versions:
        args["REF"] = versions["dolphin"]["value"]
    return args


def rebuild_args(emu_id: str) -> dict:
    """"Reconstruire": the versions already installed (the cached steps are reused, nothing is
    updated by accident). Dolphin needs none: its Dockerfile holds the installed commit."""
    if emu_id != "retroarch":
        return {}
    try:
        return build_args(emu_id, installed(emu_id))
    except Exception:
        return {}


def _pin_dolphin(job, commit: str) -> None:
    dockerfile = settings.WOLFY_IMAGES_DIR / "dolphin" / "Dockerfile"
    text = dockerfile.read_text()
    new = re.sub(r"(?m)^ARG REF=\S+$", f"ARG REF={commit}", text, count=1)
    if new != text:
        with open(dockerfile, "w") as f:  # written in place: owner and mode kept
            f.write(new)
        job.log(f"images/dolphin/Dockerfile : ARG REF={commit}")


def update(emu_id: str) -> dict:
    emu = _emu(emu_id)
    with _lock:
        if _job(emu_id):
            raise HTTPException(409, f"Une mise à jour de {emu['name']} est déjà en cours")
    latest = _latest(emu_id, refresh=True)
    if latest["error"] and not any(src["key"] in latest for src in SOURCES[emu_id]):
        raise HTTPException(502, latest["error"])
    inst = installed(emu_id)
    new = {s["key"]: latest[s["key"]] for s in SOURCES[emu_id]
           if s["key"] in latest and _is_newer(s, inst.get(s["key"]), latest[s["key"]])}
    # components not updated keep their installed version (cores: all three or none)
    versions = {**inst, **new}
    if emu_id == "retroarch" and any(c in new for c in RA_CORES):
        versions.update({c: latest[c] for c in RA_CORES if c in latest})
    args = build_args(emu_id, versions)
    names = ", ".join(s["name"] for s in SOURCES[emu_id] if s["key"] in new) or "rien de nouveau"

    def work(job):
        docker_ops.step_progress(job, f"Image {emu['image']}")
        job.log(f"À mettre à jour : {names}")
        for s in SOURCES[emu_id]:
            if s["key"] in new:
                have = inst.get(s["key"])
                job.log(f"  {s['name']} : {have['version'] if have else '?'} → {new[s['key']]['version']}")
        docker_ops.build_steps(job, emu["image"], emu["build_dir"], buildargs=args)
        if emu_id == "dolphin" and "REF" in args:
            _pin_dolphin(job, args["REF"])
        with _lock:
            _checked.pop(emu_id, None)
        job.log(f"{emu['name']} à jour : actif à la prochaine session.")

    job = docker_ops.run_job(f"Mise à jour de {emu['name']}", work)
    _jobs[emu_id] = job.id
    return job.as_dict()
