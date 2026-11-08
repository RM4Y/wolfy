"""Updates of the app Switch's emulator (the fork of images/switch/emulator.version: Eglantine, or
Lichii) from Wolfy: the newest release on GitHub, and the update job (same steps as
images/switch/update-emulator.py): the build environment of the new version, the patched emulator
compiled in it (images/switch/compile.sh: patches first, the installed version left as it was if
one no longer applies), then the image wolfy-switch:latest."""
import importlib.util
import json
import os
import re
import threading
import time

from fastapi import HTTPException

from . import docker_ops, emulators, settings

SWITCH = settings.WOLFY_IMAGES_DIR / "switch"
HOST_SWITCH = f"{settings.WOLFY_HOST_DIR}/images/switch"
HOST_BUILD = f"{settings.HOST_HOME}/.cache/wolfy-switch-build"
BUILDER = "wolfy-switch-builder"
CHECK_EVERY = 15 * 60  # GitHub allows 60 unauthenticated requests an hour
DURATIONS = settings.DATA_DIR / "switch-update.json"  # seconds each phase took last time (ETA)

_lock = threading.Lock()
_latest: dict = {}
_job_id: str | None = None


def _rel():
    """images/switch/emu_release.py (shared with update-emulator.py), loaded fresh each time."""
    spec = importlib.util.spec_from_file_location("emu_release", SWITCH / "emu_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _job():
    job = docker_ops.JOBS.get(_job_id or "")
    return job if job and job.status == "running" else None


def status(refresh: bool = False) -> dict:
    rel = _rel()
    current = rel.read()
    built = rel.read(SWITCH / "patched/bin/emulator.version")
    with _lock:
        if refresh or not _latest or time.time() - _latest.get("at", 0) > CHECK_EVERY:
            try:
                if _latest.get("repo") != current.get("EMU_REPO"):  # another fork: forget the old one
                    _latest.clear()
                _latest.update(rel.latest(current), repo=current.get("EMU_REPO"), error=None, at=time.time())
            except Exception as exc:  # offline, rate limit: shown, retried at the next check
                _latest.update(error=f"GitHub injoignable : {exc}", at=time.time())
        latest = dict(_latest)
    job = _job()
    return {
        "current": {"name": current.get("EMU_NAME"), "repo": current.get("EMU_REPO"),
                    "tag": current.get("EMU_TAG"), "published": current.get("EMU_DATE"),
                    "commit": current.get("EMU_COMMIT"), "llvm": current.get("EMU_LLVM"), "qt": current.get("EMU_QT")},
        "built_matches": all(built.get(k) == current.get(k) for k in ("EMU_REPO", "EMU_COMMIT")),
        "latest": {k: latest.get(k) for k in ("tag", "title", "published", "url")} if latest.get("tag") else None,
        "error": latest.get("error"),
        "checked": latest.get("at"),
        "update_available": bool(latest.get("tag")) and rel.newer(latest, current),
        "image": docker_ops.image_info(emulators.BY_ID["switch"]["image"]),
        "job": job.as_dict() if job else None,
    }


class Progress:
    """Progress and ETA of an update: build environment, compilation, image. A phase's share of the
    bar and its expected length come from the last update (DURATIONS, else the defaults measured on
    a Ryzen 7 5800X: cached environment ~10 s, full compilation ~9 min, image ~1 min). Within a
    phase the fraction comes from its output: Docker's "Step N/M", ninja's "[N/M]"."""
    PHASES = {"env": ("Environnement de compilation", 60), "compile": ("Compilation de l'émulateur", 560),
              "image": ("Image Switch", 60)}

    def __init__(self, job):
        self.start = time.time()
        try:
            last = json.loads(DURATIONS.read_text())
        except (OSError, ValueError):
            last = {}
        self.expected = {k: float(last.get(k) or d) for k, (_, d) in self.PHASES.items()}
        self.took: dict[str, float] = {}
        self.phase, self.phase_start, self.frac = "env", self.start, 0.0
        self.full = False  # a full compilation (only its length is kept for the next ETA)
        job.on_line, job.progress = self.line, self.snapshot

    def set(self, phase: str) -> None:
        now = time.time()
        self.took[self.phase] = now - self.phase_start
        self.phase, self.phase_start, self.frac = phase, now, 0.0

    def line(self, line: str) -> None:
        if line.startswith("== Nouvelles sources"):
            self.full = True
        if m := re.match(r"Step (\d+)/(\d+)", line):
            self.frac = (int(m[1]) - 1) / int(m[2])
        elif self.phase == "compile" and (m := re.match(r"\[(\d+)/(\d+)\]", line)):
            # the configuration before ninja is ~10 % of a full compilation
            self.frac = 0.1 + 0.9 * int(m[1]) / int(m[2])

    def snapshot(self) -> dict:
        now = time.time()
        names = list(self.PHASES)
        i = names.index(self.phase)
        elapsed = now - self.phase_start
        expected = self.expected[self.phase]
        if self.phase == "compile" and self.frac > 0.12:
            total = elapsed / self.frac  # ninja's measured rate, once well under way
        else:  # Docker steps are not even in length: the expected length, stretched if overrun
            total = max(expected, elapsed * 1.1)
        done = max(elapsed, self.frac * total)
        left = max(total - done, 0.0)
        past = sum(self.took.get(n, self.expected[n]) for n in names[:i])
        future = sum(self.expected[n] for n in names[i + 1:])
        return {"percent": round(min(99.0, 100 * (past + done) / (past + total + future)), 1),
                "phase": self.PHASES[self.phase][0], "step": f"{i + 1}/{len(names)}",
                "eta": int(left + future), "elapsed": int(now - self.start)}

    def finish(self) -> None:
        self.set("image")  # closes the image phase (took["image"])
        took = dict(self.took)
        if not self.full:
            took["compile"] = self.expected["compile"]
        try:
            DURATIONS.write_text(json.dumps({k: round(v) for k, v in took.items()}))
        except OSError:
            pass


def _build_builder(job, version: dict) -> None:
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(SWITCH / "builder.Dockerfile", arcname="builder.Dockerfile")
    buf.seek(0)
    job.log(f"== Environnement de compilation (clang {version['EMU_LLVM']}, Qt {version['EMU_QT']})")
    for chunk in docker_ops.client().api.build(fileobj=buf, custom_context=True, dockerfile="builder.Dockerfile",
                                               tag=BUILDER, rm=True, decode=True, buildargs=version):
        if "stream" in chunk:
            job.log(chunk["stream"])
        elif "error" in chunk:
            raise RuntimeError(chunk["error"])


def update(tag: str | None = None) -> dict:
    global _job_id
    with _lock:
        if _job():
            raise HTTPException(409, "Une mise à jour de l'émulateur Switch est déjà en cours")
        rel = _rel()
        current = rel.read()
        try:
            published = ""
            if not tag:
                latest = rel.latest(current)
                tag, published = latest["tag"], latest["published"]
            version = rel.version_for(tag, current, published)
        except Exception as exc:
            raise HTTPException(502, f"GitHub injoignable : {exc}")
        st = os.stat(SWITCH)
        name = current["EMU_NAME"]

        def work(job):
            progress = Progress(job)
            job.log(f"{name} {current.get('EMU_TAG')} → {tag} ({version['EMU_COMMIT'][:9]})")
            _build_builder(job, version)
            progress.set("compile")
            job.log(f"== Compilation de {name} patché")
            code = docker_ops.run_container(
                job, BUILDER, ["bash", "/switch/compile.sh"],
                [f"{HOST_SWITCH}:/switch:rw", f"{HOST_BUILD}/release:/src/build/release:rw",
                 f"{HOST_BUILD}/cpm:/src/.cache/cpm:rw"],
                user="0:0", environment={"JOBS": "10", "OWNER": f"{st.st_uid}:{st.st_gid}"},
                check=False)
            if code == 3:
                raise RuntimeError(f"un patch ne s'applique plus : {name} n'a pas été mis à jour")
            if code:
                raise RuntimeError(f"la compilation a échoué (code {code}) : {name} n'a pas été mis à jour")
            emu = emulators.BY_ID["switch"]
            progress.set("image")
            job.log(f"== Image {emu['image']}")
            docker_ops.build_steps(job, emu["image"], emu["build_dir"])
            progress.finish()
            job.log(f"{name} {tag} installé : actif à la prochaine session Switch.")

        job = docker_ops.run_job(f"Mise à jour de {name} vers {tag}", work)
        _job_id = job.id
        return job.as_dict()
