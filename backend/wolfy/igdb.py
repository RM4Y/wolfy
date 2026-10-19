"""IGDB catalogue (covers, every game of a console) for the "Mes jeux" page.

Credentials of a Twitch application (dev.twitch.tv › Applications: Client ID + Client Secret),
set in Paramètres; the secret never goes back to the browser. Romarr's platform slugs are mostly
IGDB's own (snes, wii, genesis-slash-megadrive…); the few that differ are in SLUGS.
"""
import asyncio
import re
import time
import unicodedata

import httpx
from fastapi import HTTPException

from . import store

API = "https://api.igdb.com/v4"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
PAGE = 60
# main games, compilations (Super Mario All-Stars is a cartridge), standalone expansions, remakes,
# remasters, expanded games and ports: no DLC, mods (romhacks), episodes, seasons, packs or updates
GAME_TYPES = "(0,3,4,8,9,10,11)"
# Romarr slug -> IGDB slug, where they differ
SLUGS = {"psx": "ps", "segacd": "sega-cd", "philips-cd-i": "philips-cdi", "apple2": "appleii", "c128": "c64"}
# IGDB files Virtual Console, Switch Online & co under the console too: a game out on it this long
# after its first release is such a re-release (Ocarina of Time on Wii), not one of its games
RERELEASE_GAP = 5 * 365 * 86400

_token: dict = {}  # (client_id, secret) -> (bearer, expiry)
_platforms: dict[str, int | None] = {}  # slug -> IGDB id
_lock = asyncio.Lock()  # IGDB allows 4 requests a second
_last = 0.0


def config() -> tuple[str, str]:
    st = store.get("settings")
    return st.get("igdb_client_id", ""), st.get("igdb_secret", "")


def public_config() -> dict:
    client_id, secret = config()
    return {"igdb_client_id": client_id, "igdb_secret_set": bool(secret)}


async def _bearer(client: httpx.AsyncClient, client_id: str, secret: str, refresh: bool = False) -> str:
    cached = _token.get((client_id, secret))
    if cached and cached[1] > time.time() + 60 and not refresh:
        return cached[0]
    resp = await client.post(TOKEN_URL, params={"client_id": client_id, "client_secret": secret,
                                                "grant_type": "client_credentials"})
    if resp.status_code >= 400:
        raise HTTPException(502, "Twitch refuse le Client ID / Client Secret d'IGDB (Paramètres › IGDB)")
    body = resp.json()
    _token[(client_id, secret)] = (body["access_token"], time.time() + float(body.get("expires_in", 0)))
    return body["access_token"]


async def query(endpoint: str, body: str, *, client_id: str = "", secret: str = "") -> list[dict]:
    """One Apicalypse query (IGDB's own query language, not JSON)."""
    global _last
    if not client_id:
        client_id, secret = config()
    if not (client_id and secret):
        raise HTTPException(409, "IGDB n'est pas configuré (Paramètres › IGDB)")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            refresh = False
            for _ in range(4):
                bearer = await _bearer(client, client_id, secret, refresh=refresh)
                async with _lock:
                    await asyncio.sleep(max(0.0, _last + 0.26 - time.monotonic()))
                    _last = time.monotonic()
                    resp = await client.post(f"{API}/{endpoint}", content=body, headers={
                        "Client-ID": client_id, "Authorization": f"Bearer {bearer}", "Accept": "application/json"})
                if resp.status_code == 401 and not refresh:
                    refresh = True  # expired token: a new one, once
                elif resp.status_code == 429:  # over IGDB's rate all the same: wait a little
                    await asyncio.sleep(1)
                else:
                    break
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"IGDB injoignable : {exc or type(exc).__name__}") from exc
    if resp.status_code >= 400:
        raise HTTPException(502, f"IGDB a refusé la requête ({resp.status_code}) : {resp.text[:200]}")
    return resp.json()


async def test(client_id: str, secret: str) -> dict:
    await query("platforms", 'fields id; where slug = "snes";', client_id=client_id, secret=secret)
    return {"ok": True}


async def _platform_id(slug: str) -> int | None:
    if slug not in _platforms:
        igdb_slug = SLUGS.get(slug, slug)
        rows = await query("platforms", f'fields id; where slug = "{_quote(igdb_slug)}";')
        _platforms[slug] = rows[0]["id"] if rows else None
    return _platforms[slug]


def _quote(text: str) -> str:
    return text.replace("\\", "").replace('"', "")


def _cover(row: dict) -> str:
    url = (row.get("cover") or {}).get("url", "")
    return "https:" + url.replace("/t_thumb/", "/t_cover_big/") if url else ""


def _words(text: str) -> list[str]:
    """"Lapin crétin" -> ["lapin", "cretin"]: no accents (IGDB's alternative names often have none),
    no plural s, so each word matches as a substring."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", text)]


async def _by_alias(q: str, where: str, fields: str) -> list[dict]:
    """Games whose alternative names (French titles…) hold every word of the search:
    IGDB's own search only looks at the main, usually English, name."""
    words = _words(q)
    if not words:
        return []
    match = " & ".join(f'name ~ *"{w}"*' for w in words)
    alias = {}
    for row in await query("alternative_names", f"fields name,game; where {match}; limit 50;"):
        alias.setdefault(row["game"], row["name"])
    if not alias:
        return []
    rows = await query("games", f"{fields} where id = ({','.join(map(str, alias))}) & {where}; "
                                f"sort total_rating_count desc; limit {PAGE};")
    # the other name is shown only when it is what matched, not the main one
    return [{**r, "alias": "" if all(w in " ".join(_words(r.get("name", ""))) for w in words) else alias[r["id"]]}
            for r in rows]


def _native(row: dict, pid: int) -> bool:
    """False for a re-release: out on this console long after the game first came out."""
    first = row.get("first_release_date")
    dates = [d["date"] for d in row.get("release_dates") or [] if d.get("platform") == pid and d.get("date")]
    return not (first and dates) or min(dates) - first <= RERELEASE_GAP


async def catalog(platform: str, q: str = "", offset: int = 0, sort: str = "popular") -> dict:
    """One page of a console's games: the best known first or A to Z, or the matches of a search.

    Re-releases are dropped after the query, so a page may take several IGDB pages: `next` is
    the IGDB offset to continue from."""
    pid = await _platform_id(platform)
    if pid is None:
        return {"items": [], "more": False, "error": "Console inconnue d'IGDB"}
    where = f"platforms = ({pid}) & game_type = {GAME_TYPES}"
    fields = "fields name,cover.url,first_release_date,total_rating,release_dates.platform,release_dates.date;"
    if q.strip():
        head = f'search "{_quote(q.strip())}"; {fields} where {where};'
    else:
        # popular: by number of ratings, the console's well-known games first
        order = "name asc" if sort == "name" else "total_rating_count desc"
        head = f"{fields} where {where}; sort {order};"
    kept, more = [], True
    if q.strip() and not offset:
        kept = [r for r in await _by_alias(q.strip(), where, fields) if _native(r, pid)]
    seen = {r["id"] for r in kept}
    for _ in range(5):
        rows = await query("games", f"{head} limit {PAGE}; offset {offset};")
        offset += len(rows)
        more = len(rows) == PAGE
        kept += [r for r in rows if _native(r, pid) and r["id"] not in seen]
        if len(kept) >= PAGE // 2 or not more:
            break
    items = [{
        "id": r["id"],
        "title": r.get("name", ""),
        "alias": r.get("alias", ""),
        "cover": _cover(r),
        "year": time.gmtime(r["first_release_date"]).tm_year if r.get("first_release_date") else None,
        "rating": round(r["total_rating"] / 10, 1) if r.get("total_rating") else None,
    } for r in kept]
    return {"items": items, "more": more, "next": offset}


# ------------------------------------------------------------ library covers
# Romarr's "Folder" library knows file names only: each game is looked up once on IGDB, in the
# background, and what it is (or {} when nothing matches) kept in the store section "igdb_library"
_identify_task: asyncio.Task | None = None


async def identify(name: str, platform: str) -> dict:
    """The IGDB game behind a library name: {title, cover, year}, {} when none matches."""
    pid = await _platform_id(platform)
    if pid is None:
        return {}
    fields = "fields name,cover.url,first_release_date,game_type;"
    where = f"platforms = ({pid}) & game_type = {GAME_TYPES}"
    rows = (await query("games", f'search "{_quote(name)}"; {fields} where {where}; limit 10;')
            or await _by_alias(name, where, fields)
            or await query("games", f'search "{_quote(name)}"; {fields} where platforms = ({pid}); limit 10;'))
    # still nothing: words left over from a release name ("… Super"), dropped from the end
    words = name.split()
    for n in range(len(words) - 1, max(len(words) - 4, 1), -1):
        if rows:
            break
        rows = await query("games", f'search "{_quote(" ".join(words[:n]))}"; {fields} where {where}; limit 10;')
    if not rows:
        return {}
    # IGDB's search can put "Wii Sports + Wii Sports Resort" first: the very name, then no compilation
    wanted = _words(name)
    r = min(rows, key=lambda r: (_words(r.get("name", "")) != wanted, r.get("game_type") == 3))
    return {"title": r.get("name", ""), "cover": _cover(r),
            "year": time.gmtime(r["first_release_date"]).tm_year if r.get("first_release_date") else None}


async def _identify_all(games: list[dict]) -> None:
    for game in games:
        try:
            found = await identify(game["name"], game["platform"])
        except HTTPException as exc:  # IGDB unconfigured or down: try again on the next visit
            print(f"IGDB: bibliothèque non identifiée ({exc.detail})", flush=True)
            return
        # with the name looked up: a better cleanup of file names looks the game up again
        store.put("igdb_library", game["id"], {**found, "name": game["name"]})


def dress_library(lib: dict, q: str = "", platform: str = "") -> dict:
    """Romarr's library with IGDB's title, cover and year, filtered by console and search words."""
    global _identify_task
    known = store.get("igdb_library")
    games = lib["items"]
    missing = [g for g in games if known.get(g["id"], {}).get("name") != g["name"]]
    if missing and all(config()) and (_identify_task is None or _identify_task.done()):
        _identify_task = asyncio.create_task(_identify_all(missing))
    for g in games:
        found = known.get(g["id"]) or {}
        g.update(title=found.get("title") or g["name"], cover=found.get("cover", ""), year=found.get("year"))
    if platform:
        games = [g for g in games if g["platform"] == platform]
    if words := _words(q):
        games = [g for g in games if all(w in " ".join(_words(f"{g['name']} {g['title']}")) for w in words)]
    games.sort(key=lambda g: g["title"].lower())
    identifying = bool(missing) and _identify_task is not None and not _identify_task.done()
    return {**lib, "items": games, "total": len(games), "identifying": identifying}
