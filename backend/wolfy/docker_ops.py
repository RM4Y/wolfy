"""Docker side: Wolf container lifecycle, app containers, image builds/pulls, background jobs."""
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Callable

import docker
from docker.errors import APIError, ImageNotFound, NotFound
from fastapi import HTTPException

from . import settings, wolf_api

_client = None


def client() -> docker.DockerClient:
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
        except docker.errors.DockerException as exc:
            raise HTTPException(503, f"Docker injoignable : {exc}")
    return _client


def wolf_container():
    try:
        return client().containers.get(settings.WOLF_CONTAINER)
    except NotFound:
        raise HTTPException(404, f"Conteneur « {settings.WOLF_CONTAINER} » introuvable")


# ------------------------------------------------------------------- Wolf

def wolf_status() -> dict:
    c = wolf_container()
    c.reload()
    state = c.attrs["State"]
    return {
        "status": state["Status"],
        "running": state["Running"],
        "started_at": state.get("StartedAt"),
        "restart_count": c.attrs.get("RestartCount", 0),
        "image": c.attrs["Config"]["Image"],
        "api": wolf_api.available(),
    }


def _wait_socket(present: bool, timeout: float = 30) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if wolf_api.available() == present:
            return
        time.sleep(0.5)


def wolf_action(action: str) -> None:
    c = wolf_container()
    if action == "restart":
        c.restart(timeout=20)
        _wait_socket(True)
    elif action == "stop":
        c.stop(timeout=20)
    elif action == "start":
        c.start()
        _wait_socket(True)
    else:
        raise HTTPException(400, "Action inconnue")


_config_lock = threading.Lock()


def with_wolf_stopped(change: Callable[[], object]):
    """Run `change` (a config.toml edit) while Wolf is stopped, then start Wolf again.

    Wolf rewrites config.toml itself, so editing it while running would be overwritten.
    """
    with _config_lock:
        c = wolf_container()
        was_running = c.status == "running" or c.attrs["State"]["Running"]
        if was_running:
            c.stop(timeout=20)
        try:
            return change()
        finally:
            if was_running:
                c.start()
                _wait_socket(True)


def wolf_logs(tail: int = 300) -> str:
    raw = wolf_container().logs(tail=tail, timestamps=False)
    return raw.decode(errors="replace")


# ------------------------------------------------------------------- app containers

def app_containers(runner_names: set[str]) -> list[dict]:
    """Containers started by Wolf for apps (named after the runner, e.g. WolfSwitch_<id>)."""
    out = []
    for c in client().containers.list(all=True):
        name = c.name
        if name == settings.WOLF_CONTAINER:
            continue
        app = next((r for r in runner_names if name == r or name.startswith(r + "_")), None)
        is_pulse = name.startswith("WolfPulseAudio")
        if app is None and not is_pulse:
            continue
        out.append({
            "id": c.short_id,
            "name": name,
            "app": app or "PulseAudio",
            "image": c.attrs["Config"]["Image"],
            "status": c.status,
            "created": c.attrs["Created"],
        })
    return sorted(out, key=lambda x: x["created"], reverse=True)


def container_action(name: str, action: str, runner_names: set[str]) -> None:
    allowed = {c["name"] for c in app_containers(runner_names)}
    if name not in allowed:
        raise HTTPException(403, "Ce conteneur n'est pas géré par Wolf")
    c = client().containers.get(name)
    if action == "stop":
        c.stop(timeout=10)
    elif action == "remove":
        c.remove(force=True)
    else:
        raise HTTPException(400, "Action inconnue")


def prune_app_containers(runner_names: set[str]) -> int:
    removed = 0
    for info in app_containers(runner_names):
        if info["status"] in ("exited", "dead", "created") and info["app"] != "PulseAudio":
            client().containers.get(info["name"]).remove()
            removed += 1
    return removed


# ------------------------------------------------------------------- images

def image_info(ref: str) -> dict:
    try:
        img = client().images.get(ref)
    except ImageNotFound:
        return {"ref": ref, "present": False}
    except APIError as exc:
        return {"ref": ref, "present": False, "error": str(exc)}
    return {
        "ref": ref,
        "present": True,
        "id": img.short_id.replace("sha256:", ""),
        "created": img.attrs.get("Created"),
        "size": img.attrs.get("Size"),
    }


def build_context(build_dir: str | None):
    if not build_dir:
        return None
    path = settings.WOLF_IMAGES_DIR / build_dir
    return path if (path / "Dockerfile").is_file() else None


# ------------------------------------------------------------------- jobs

class Job:
    def __init__(self, title: str):
        self.id = uuid.uuid4().hex[:10]
        self.title = title
        self.status = "running"
        self.lines: deque[str] = deque(maxlen=2000)
        self.started = datetime.now().isoformat(timespec="seconds")
        self.finished: str | None = None

    def log(self, line: str) -> None:
        for part in str(line).splitlines():
            if part.strip():
                self.lines.append(part.rstrip())

    def as_dict(self, with_log: bool = False) -> dict:
        d = {"id": self.id, "title": self.title, "status": self.status,
             "started": self.started, "finished": self.finished}
        if with_log:
            d["log"] = list(self.lines)
        return d


JOBS: dict[str, Job] = {}


def run_job(title: str, work: Callable[[Job], None]) -> Job:
    job = Job(title)
    JOBS[job.id] = job
    for old in sorted(JOBS.values(), key=lambda j: j.started)[:-20]:
        JOBS.pop(old.id, None)

    def target():
        try:
            work(job)
            job.status = "success"
        except Exception as exc:  # reported in the job log
            job.log(f"ERREUR : {exc}")
            job.status = "error"
        job.finished = datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=target, daemon=True).start()
    return job


def build_image(ref: str, build_dir: str) -> Job:
    ctx = build_context(build_dir)
    if ctx is None:
        raise HTTPException(404, f"Pas de Dockerfile dans {settings.WOLF_IMAGES_DIR / build_dir}")

    def work(job: Job):
        job.log(f"Construction de {ref} depuis {ctx}")
        for chunk in client().api.build(path=str(ctx), tag=ref, rm=True, pull=True, decode=True):
            if "stream" in chunk:
                job.log(chunk["stream"])
            elif "status" in chunk:
                job.log(f"{chunk['status']} {chunk.get('progress', '')}")
            elif "error" in chunk:
                raise RuntimeError(chunk["error"])
        job.log("Image construite.")

    return run_job(f"Construction {ref}", work)


def pull_image(ref: str) -> Job:
    def work(job: Job):
        repo, _, tag = ref.rpartition(":") if ":" in ref.split("/")[-1] else (ref, "", "latest")
        job.log(f"Téléchargement de {repo}:{tag}")
        seen = set()
        for chunk in client().api.pull(repo, tag=tag, stream=True, decode=True):
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
            key = (chunk.get("id"), chunk.get("status"))
            if key not in seen and "Downloading" not in chunk.get("status", ""):
                seen.add(key)
                job.log(f"{chunk.get('id', '')} {chunk.get('status', '')}")
        job.log("Image à jour.")

    return run_job(f"Mise à jour {ref}", work)
