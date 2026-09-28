"""Client for Wolf's REST API, served on a UNIX socket (WOLF_SOCKET_PATH in the Wolf container)."""
import os
import socket

import httpx
from fastapi import HTTPException

from . import settings


class WolfUnavailable(HTTPException):
    def __init__(self, detail: str):
        super().__init__(503, f"API Wolf injoignable : {detail}")


def _client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=settings.WOLF_SOCKET)
    return httpx.AsyncClient(transport=transport, base_url="http://wolf", timeout=10)


async def call(method: str, path: str, payload: dict | None = None) -> dict:
    if not available():
        raise WolfUnavailable(f"pas de réponse sur {settings.WOLF_SOCKET} (Wolf arrêté ou en démarrage ?)")
    try:
        async with _client() as client:
            resp = await client.request(method, f"/api/v1/{path}", json=payload)
    except httpx.HTTPError as exc:
        raise WolfUnavailable(str(exc) or type(exc).__name__) from exc
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(502, f"Réponse Wolf invalide ({resp.status_code}) : {resp.text[:200]}")
    if resp.status_code >= 400 or data.get("success") is False:
        raise HTTPException(502, f"Wolf a refusé la requête : {data.get('error') or resp.text[:200]}")
    return data


async def get(path: str) -> dict:
    return await call("GET", path)


async def post(path: str, payload: dict) -> dict:
    return await call("POST", path, payload)


def available() -> bool:
    """Wolf answers on its socket (the file itself outlives Wolf in the shared volume)."""
    if not os.path.exists(settings.WOLF_SOCKET):
        return False
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1)
            s.connect(settings.WOLF_SOCKET)
        return True
    except OSError:
        return False
