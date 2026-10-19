"""Client for Romarr (the *arr for ROMs): game requests from the "Mes jeux" page.

Address and API key are set in Paramètres (store section "settings"); the key never goes
back to the browser. Romarr takes it in the X-Api-Key header (Romarr › Settings › General).
"""
import re
from pathlib import PurePosixPath

import httpx
from fastapi import HTTPException

from . import store


def config() -> tuple[str, str]:
    st = store.get("settings")
    return st.get("romarr_url", ""), st.get("romarr_key", "")


def public_config() -> dict:
    url, key = config()
    return {"romarr_url": url, "romarr_key_set": bool(key)}


async def call(method: str, path: str, *, url: str = "", key: str = "", timeout: float = 15,
               **kwargs) -> dict | list:
    """One Romarr API call; url / key default to the saved ones (the connection test passes its own)."""
    if not url:
        url, saved_key = config()
        key = key or saved_key
    if not url:
        raise HTTPException(409, "Romarr n'est pas configuré (Paramètres › Romarr)")
    headers = {"X-Api-Key": key} if key else {}
    try:
        async with httpx.AsyncClient(base_url=url, headers=headers, timeout=timeout) as client:
            resp = await client.request(method, path, **kwargs)
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Romarr ne répond pas (délai dépassé)") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Romarr injoignable : {exc or type(exc).__name__}") from exc
    if resp.status_code == 401:
        raise HTTPException(502, "Romarr refuse la clé API (Paramètres › Romarr)")
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(502, f"Réponse Romarr invalide ({resp.status_code}) : {resp.text[:200]}")
    if resp.status_code >= 400 and resp.status_code != 404:
        detail = data.get("error") if isinstance(data, dict) else None
        raise HTTPException(502, f"Romarr a refusé la requête : {detail or resp.text[:200]}")
    return data


async def test(url: str, key: str) -> dict:
    """Checks the address and the key: /api/health is open, /api/v1/queue needs the key."""
    health = await call("GET", "/api/health", url=url, key=key, timeout=8)
    await call("GET", "/api/v1/queue", url=url, key=key, timeout=8)
    return {"ok": True, "health": health}


async def overview() -> dict:
    """Platforms Romarr knows, wanted list and downloads in flight."""
    platforms = await call("GET", "/api/platforms")
    wanted = await call("GET", "/api/v1/wanted/missing")
    queue = await call("GET", "/api/v1/queue")
    return {
        "platforms": [{"slug": p["slug"], "name": p["name"]} for p in platforms],
        "wanted": wanted.get("items", []),
        "queue": queue.get("items", []),
    }


# what release names add to a title: version, region, language, dump format
_NOISE = re.compile(r"\b(v\d+(\.\d+)*|rev\s?\d+|eur|europe|usa|us|jpn|japan|pal|ntsc|multi\d*|eng?|fr|"
                    r"xci|xcz|nsp|nsz|iso|wbfs|cso|chd|psn|update|dlc)\b", re.I)


def clean_name(name: str) -> str:
    """"Wii Sports (USA) (Rev 1)" -> "Wii Sports", "Super_Mario_Galaxy_2" -> "Super Mario Galaxy 2",
    "Mario Kart Wii RMCP01" -> "Mario Kart Wii", "Super Mario Bros Wonder v1.0 Eur XCi - CLC" ->
    "Super Mario Bros Wonder": the name to look a game up by."""
    name = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", name)
    # a release group: "… - CLC", "Zelda.Tears.of.the.Kingdom.NSP-VENOM"
    name = re.sub(r"\s-\s?[A-Z0-9]{3,8}\s*$", " ", name.strip())
    if "." in name and " " not in name:
        name = re.sub(r"-[A-Z0-9]{3,8}$", "", name)
    name = re.sub(r"\s[A-Z0-9]{4}\d{2}$", " ", name.strip())  # a Wii / GameCube disc id
    name = _NOISE.sub(" ", name)
    name = re.sub(r"[_.]+", " ", name)
    return re.sub(r"\s+", " ", name).strip(" -")


async def library() -> dict:
    """Every game of Romarr's library, one per game: Romarr's "Folder" library lists files, so a game
    kept in a folder of its own (bin + cue, a PS3 game's tree) comes as several entries whose
    platform is a folder name. The platform is the known one in the path, the game that folder."""
    slugs = {p["slug"] for p in await call("GET", "/api/platforms")}
    data = await call("GET", "/api/v1/game", params={"limit": 5000, "sort": "name"}, timeout=30)
    games: dict[tuple, dict] = {}
    for item in data.get("items") or []:
        parts = PurePosixPath(item["id"]).parts
        at = next((i for i, part in enumerate(parts) if part in slugs), None)
        platform = parts[at] if at is not None else item.get("platform", "")
        folder = parts[at + 1] if at is not None and len(parts) > at + 2 else None
        game = games.setdefault((platform, folder or item["id"]), {
            "id": f"{platform}/{folder or item['name']}", "platform": platform, "files": 0,
            "name": item["name"], "folder": folder})
        game["files"] += 1
    for game in games.values():
        # one file in its folder: the file is better named ("LocoRoco (Europe)", not "loco-roco-europe-en-fr…")
        raw = game.pop("folder") if game["files"] > 1 else game["name"]
        game["name"] = clean_name(raw) or raw
        del game["files"]
    return {"items": sorted(games.values(), key=lambda g: g["name"].lower()),
            **{k: data.get(k) for k in ("loading", "error", "message")}}


async def discover(shelf: str) -> dict:
    return await call("GET", "/api/v1/discover", params={"shelf": shelf, "limit": 40}, timeout=30)


async def request(game: str, platform: str) -> dict:
    # Romarr searches its indexers before answering: can take a while
    return await call("POST", "/api/request", json={"game": game, "platform": platform}, timeout=180)


async def drop(game: str, platform: str) -> dict:
    return await call("DELETE", "/api/v1/wanted/missing", params={"game": game, "platform": platform})
