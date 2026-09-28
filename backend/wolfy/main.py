"""Wolfy: admin web UI for Wolf (games-on-whales) — pairing, sessions, apps/emulators, maintenance."""
import asyncio
import hmac
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, docker_ops, eden_config, emulators, settings, store, wolf_api, wolf_config

app = FastAPI(title="Wolfy", docs_url="/api/docs", openapi_url="/api/openapi.json")
public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(auth.require_admin)])


# ------------------------------------------------------------------- auth

class Login(BaseModel):
    password: str


@public.get("/auth")
def auth_status(request: Request):
    return {"logged_in": auth.is_logged_in(request), "configured": bool(settings.ADMIN_PASSWORD)}


@public.post("/auth/login")
def login(body: Login, response: Response):
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(503, "WOLFY_ADMIN_PASSWORD n'est pas défini")
    if not auth.check_password(body.password):
        time.sleep(1)
        raise HTTPException(401, "Mot de passe incorrect")
    auth.open_session(response)
    return {"ok": True}


@public.post("/auth/logout")
def logout(response: Response):
    auth.close_session(response)
    return {"ok": True}


# ------------------------------------------------------------------- hooks (called by Wolf sessions)

class SessionHook(BaseModel):
    session_id: str
    token: str


@public.post("/hooks/session-stop")
async def hook_session_stop(body: SessionHook):
    """Quit combo pressed in a Switch session: end that Moonlight session cleanly."""
    if not hmac.compare_digest(body.token, settings.hook_token()):
        raise HTTPException(403, "Jeton invalide")
    await wolf_api.post("sessions/stop", {"session_id": body.session_id})
    return {"ok": True}


# ------------------------------------------------------------------- overview

@api.get("/overview")
async def overview():
    status = await run_in_threadpool(docker_ops.wolf_status)
    doc = await run_in_threadpool(wolf_config.load)
    data = {"wolf": status, "hostname": wolf_config.hostname(doc),
            "sessions": [], "pending": [], "clients": 0, "api_error": None}
    if status["api"]:
        try:
            data["sessions"] = (await wolf_api.get("sessions")).get("sessions", [])
            data["pending"] = (await wolf_api.get("pair/pending")).get("requests", [])
            data["clients"] = len((await wolf_api.get("clients")).get("clients", []))
        except HTTPException as exc:
            data["api_error"] = exc.detail
    data["apps"] = sum(len(p["apps"]) for p in wolf_config.list_profiles(doc) if p["moonlight"])
    data["gpu_driver"] = _gpu_driver()
    return data


def _gpu_driver() -> str | None:
    try:
        line = Path("/proc/driver/nvidia/version").read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    m = re.search(r"\s(\d+\.\d+(?:\.\d+)?)\s", line)
    return m.group(1) if m else None


# ------------------------------------------------------------------- pairing / clients

class PairBody(BaseModel):
    pair_secret: str
    pin: str = Field(pattern=r"^\d{4}$")
    name: str = ""
    client_ip: str = ""


@api.get("/pairing")
async def pairing():
    pending = (await wolf_api.get("pair/pending")).get("requests", [])
    clients = (await wolf_api.get("clients")).get("clients", [])
    names = store.get("clients")
    for c in clients:
        c["name"] = names.get(c["client_id"], {}).get("name", "")
        c["paired_at"] = names.get(c["client_id"], {}).get("paired_at")
        c["client_ip"] = names.get(c["client_id"], {}).get("client_ip", "")
    return {"pending": pending, "clients": clients}


@api.post("/pairing/pair")
async def pair(body: PairBody):
    before = {c["client_id"] for c in (await wolf_api.get("clients")).get("clients", [])}
    await wolf_api.post("pair/client", {"pair_secret": body.pair_secret, "pin": body.pin})
    # the client id only exists once Moonlight finishes the handshake
    new_id = None
    for _ in range(20):
        after = {c["client_id"] for c in (await wolf_api.get("clients")).get("clients", [])}
        if new := after - before:
            new_id = new.pop()
            break
        await asyncio.sleep(0.5)
    if new_id:
        store.put("clients", new_id, {
            "name": body.name.strip() or f"Appareil {body.client_ip or new_id[-4:]}",
            "client_ip": body.client_ip,
            "paired_at": time.strftime("%Y-%m-%d %H:%M"),
        })
    return {"ok": True, "client_id": new_id}


class ClientUpdate(BaseModel):
    name: str | None = None
    settings: dict | None = None


@api.patch("/clients/{client_id}")
async def update_client(client_id: str, body: ClientUpdate):
    if body.name is not None:
        meta = store.get("clients").get(client_id, {})
        store.put("clients", client_id, {**meta, "name": body.name.strip()})
    if body.settings:
        allowed = {"run_uid", "run_gid", "controllers_override", "mouse_acceleration",
                   "v_scroll_acceleration", "h_scroll_acceleration", "app_state_folder"}
        payload = {k: v for k, v in body.settings.items() if k in allowed}
        await wolf_api.post("clients/settings", {"client_id": client_id, **payload})
    return {"ok": True}


@api.delete("/clients/{client_id}")
async def unpair(client_id: str):
    await wolf_api.post("unpair/client", {"client_id": client_id})
    store.put("clients", client_id, None)
    return {"ok": True}


# ------------------------------------------------------------------- sessions

@api.get("/sessions")
async def sessions():
    data = (await wolf_api.get("sessions")).get("sessions", [])
    names = store.get("clients")
    apps = {}
    try:
        apps = {a["id"]: a["title"] for a in (await wolf_api.get("apps")).get("apps", [])}
    except HTTPException:
        pass
    for s in data:
        s["client_name"] = names.get(str(s.get("client_id")), {}).get("name", "")
        s["app_title"] = apps.get(str(s.get("app_id")), "")
    return {"sessions": data}


class SessionStop(BaseModel):
    session_id: str


@api.post("/sessions/stop")
async def stop_session(body: SessionStop):
    await wolf_api.post("sessions/stop", {"session_id": body.session_id})
    return {"ok": True}


# ------------------------------------------------------------------- apps & emulators

class AppBody(BaseModel):
    title: str
    icon: str = ""
    emulator: str = "custom"
    image: str
    rom_dir: str = ""
    mounts: list[str] = []
    env: list[str] = []
    devices: list[str] = []
    ports: list[str] = []
    base_create_json: str = emulators.BASE_CREATE_JSON
    start_virtual_compositor: bool = True
    runner_type: str = "docker"
    runner_name: str = ""
    notes: str = ""


@api.get("/profiles")
def profiles():
    return {"profiles": wolf_config.list_profiles(wolf_config.load())}


@api.get("/emulators")
def emulator_catalog():
    out = []
    for emu in emulators.EMULATORS:
        info = docker_ops.image_info(emu["image"]) if emu["image"] else {"present": False}
        ctx = docker_ops.build_context(emu["build_dir"])
        out.append({**emu, "image_info": info, "buildable": ctx is not None,
                    "pullable": ctx is None and "/" in emu["image"]})
    return {"emulators": out, "base_create_json": emulators.BASE_CREATE_JSON}


def _apply(change, reason: str):
    def run():
        doc = wolf_config.load()
        result = change(doc)
        wolf_config.save(doc, reason)
        return result
    return docker_ops.with_wolf_stopped(run)


@api.post("/profiles/{profile_id}/apps")
def create_app(profile_id: str, body: AppBody):
    name = _apply(lambda doc: wolf_config.upsert_app(doc, profile_id, None, body.model_dump()),
                  f"ajout-{body.title}")
    return {"ok": True, "runner_name": name}


@api.put("/profiles/{profile_id}/apps/{index}")
def update_app(profile_id: str, index: int, body: AppBody):
    _apply(lambda doc: wolf_config.upsert_app(doc, profile_id, index, body.model_dump()),
           f"modif-{body.title}")
    return {"ok": True}


@api.delete("/profiles/{profile_id}/apps/{index}")
def delete_app(profile_id: str, index: int):
    _apply(lambda doc: wolf_config.delete_app(doc, profile_id, index), "suppression-app")
    return {"ok": True}


class Move(BaseModel):
    delta: int = Field(ge=-1, le=1)


@api.post("/profiles/{profile_id}/apps/{index}/move")
def move_app(profile_id: str, index: int, body: Move):
    _apply(lambda doc: wolf_config.move_app(doc, profile_id, index, body.delta), "ordre-apps")
    return {"ok": True}


# ------------------------------------------------------------------- emulator settings (Eden)

@api.get("/emulator-settings/eden")
def eden_settings():
    return eden_config.read()


class SettingChange(BaseModel):
    section: str
    key: str
    value: bool | int | float | str | None = None
    raw: str | None = None
    reset: bool = False


class SettingsUpdate(BaseModel):
    changes: list[SettingChange]
    mtime: float | None = None


@api.put("/emulator-settings/eden")
def update_eden_settings(body: SettingsUpdate):
    changes = [c.model_dump(exclude_none=True) for c in body.changes]
    return {"changed": eden_config.write(changes, body.mtime)}


class HomeCombo(BaseModel):
    enabled: bool = True
    modifier: str = "start"
    button: str = "a"
    quit_enabled: bool = True
    quit_combo: str = "start+guide"
    quit_hold: float = 1.0


@api.get("/emulator-settings/eden/home-combo")
def get_home_combo():
    return eden_config.read_combo()


@api.put("/emulator-settings/eden/home-combo")
def set_home_combo(body: HomeCombo):
    return eden_config.write_combo(body.model_dump())


@api.get("/emulator-settings/eden/wolfy")
def get_wolfy_eden():
    return eden_config.read_wolfy()


class MenuResolution(BaseModel):
    value: int | None = None


@api.put("/emulator-settings/eden/wolfy/menu-resolution")
def set_menu_resolution(body: MenuResolution):
    eden_config.write_menu_resolution(body.value)
    return eden_config.read_wolfy()


@api.post("/emulator-settings/eden/backups/{name}/restore")
def restore_eden_settings(name: str):
    eden_config.restore(name)
    return {"ok": True}


# ------------------------------------------------------------------- covers

@api.get("/covers")
def covers():
    settings.WOLF_COVERS_DIR.mkdir(parents=True, exist_ok=True)
    return {"dir": str(settings.WOLF_COVERS_DIR),
            "covers": sorted(p.name for p in settings.WOLF_COVERS_DIR.glob("*.png"))}


@api.post("/covers")
async def upload_cover(file: UploadFile = File(...)):
    data = await file.read()
    if not data.startswith(b"\x89PNG"):
        raise HTTPException(400, "Moonlight n'accepte que des PNG")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Image trop lourde (5 Mo max)")
    stem = re.sub(r"[^a-z0-9]+", "-", Path(file.filename or "cover").stem.lower()).strip("-") or "cover"
    dest = settings.WOLF_COVERS_DIR / f"{stem}.png"
    dest.write_bytes(data)
    return {"path": str(dest), "name": dest.name}


@api.get("/covers/{name}")
def cover(name: str):
    path = settings.WOLF_COVERS_DIR / name
    if "/" in name or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


# ------------------------------------------------------------------- maintenance

class WolfAction(BaseModel):
    action: str = Field(pattern="^(restart|stop|start)$")


@api.post("/wolf")
def wolf_action(body: WolfAction):
    docker_ops.wolf_action(body.action)
    return docker_ops.wolf_status()


@api.get("/wolf/logs")
def wolf_logs(tail: int = 300):
    return {"logs": docker_ops.wolf_logs(min(max(tail, 10), 5000))}


@api.get("/maintenance")
def maintenance():
    doc = wolf_config.load()
    cfg_dir = settings.WOLF_CONFIG.parent
    dumps = [{"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
             for p in sorted(cfg_dir.glob("backtrace.*.dump"), reverse=True)]
    return {
        "containers": docker_ops.app_containers(wolf_config.all_runner_names(doc)),
        "backtraces": dumps,
        "backups": wolf_config.list_backups(),
        "images": [docker_ops.image_info(i) for i in sorted(wolf_config.all_images(doc))],
    }


class ContainerAction(BaseModel):
    action: str = Field(pattern="^(stop|remove)$")


@api.post("/containers/{name}")
def container_action(name: str, body: ContainerAction):
    docker_ops.container_action(name, body.action, wolf_config.all_runner_names(wolf_config.load()))
    return {"ok": True}


@api.post("/containers/prune")
def prune_containers():
    return {"removed": docker_ops.prune_app_containers(wolf_config.all_runner_names(wolf_config.load()))}


@api.delete("/backtraces")
def clear_backtraces():
    removed = 0
    for p in settings.WOLF_CONFIG.parent.glob("backtrace.*.dump"):
        p.unlink()
        removed += 1
    return {"removed": removed}


@api.post("/backups/{name}/restore")
def restore_backup(name: str):
    docker_ops.with_wolf_stopped(lambda: wolf_config.restore_backup(name))
    return {"ok": True}


@api.get("/backups/{name}")
def download_backup(name: str):
    path = wolf_config.BACKUP_DIR / name
    if "/" in name or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="text/plain", filename=name)


class ImageJob(BaseModel):
    image: str
    emulator: str | None = None


@api.post("/images/build")
def build(body: ImageJob):
    emu = emulators.BY_ID.get(body.emulator or "")
    if not emu or not emu["build_dir"]:
        raise HTTPException(400, "Cet émulateur n'a pas d'image locale à construire")
    return docker_ops.build_image(emu["image"], emu["build_dir"]).as_dict()


@api.post("/images/pull")
def pull(body: ImageJob):
    if "/" not in body.image:
        raise HTTPException(400, "Image locale : utilise « Construire »")
    return docker_ops.pull_image(body.image).as_dict()


@api.get("/jobs")
def jobs():
    return {"jobs": [j.as_dict() for j in sorted(docker_ops.JOBS.values(),
                                                   key=lambda j: j.started, reverse=True)]}


@api.get("/jobs/{job_id}")
def job(job_id: str):
    j = docker_ops.JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "Tâche inconnue")
    return j.as_dict(with_log=True)


app.include_router(public)
app.include_router(api)

try:
    eden_config.ensure_hook()
except Exception as exc:  # Eden config not mounted: the quit combo just stays off
    print(f"hook not written: {exc}", flush=True)


# ------------------------------------------------------------------- frontend (built SPA)

if settings.STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=settings.STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = settings.STATIC_DIR / path
        if path and candidate.is_file() and settings.STATIC_DIR in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(settings.STATIC_DIR / "index.html")
