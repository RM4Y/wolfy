"""Accounts (store section "users") and the signed session cookie.

An admin sees everything; any other account only the tabs ticked for it in Paramètres › Comptes.
The very first account, an admin, is created from the login page: while there is none, creating it
asks for WOLFY_ADMIN_PASSWORD (when set), so no stranger reaching the page first can claim Wolfy.
"""
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import settings, store

COOKIE = "wolfy_session"
_signer = TimestampSigner(settings.secret_key(), salt="wolfy-session")
# the tabs an account other than an admin can be given (route ids of the frontend)
TABS = ("dashboard", "pairing", "sessions", "games")
NAME = re.compile(r"^[a-z0-9._-]{2,32}$")


def users() -> dict[str, dict]:
    return store.get("users")


def _hash(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def hashed(password: str) -> dict:
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _hash(password, salt)}


def check_password(name: str, password: str) -> dict | None:
    """The account, when the name and password are right."""
    user = users().get(name.strip().lower())
    if user and hmac.compare_digest(_hash(password, user["salt"]), user["hash"]):
        return user
    return None


def check_setup_password(password: str) -> bool:
    if not settings.ADMIN_PASSWORD:
        return True
    return hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())


def open_session(response: Response, name: str, user: dict) -> None:
    # the version is bumped by a password change: older cookies of the account stop working
    token = _signer.sign(f"{name}:{user.get('version', 0)}".encode()).decode()
    response.set_cookie(
        COOKIE, token, max_age=settings.SESSION_HOURS * 3600,
        httponly=True, samesite="strict",
    )


def close_session(response: Response) -> None:
    response.delete_cookie(COOKIE)


def current(request: Request) -> dict | None:
    """The logged-in account ({name, role, tabs}), None when nobody is."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        name, _, version = _signer.unsign(token, max_age=settings.SESSION_HOURS * 3600).decode().partition(":")
    except (BadSignature, SignatureExpired):
        return None
    user = users().get(name)
    if not user or str(user.get("version", 0)) != version:
        return None  # deleted, or its password changed since
    return public(name, user)


def public(name: str, user: dict) -> dict:
    admin = user.get("role") == "admin"
    return {"name": name, "role": "admin" if admin else "user",
            "tabs": list(TABS) if admin else [t for t in user.get("tabs", []) if t in TABS]}


def require_user(request: Request) -> dict:
    user = current(request)
    if not user:
        raise HTTPException(401, "Non connecté")
    return user


def require_admin(request: Request) -> None:
    if require_user(request)["role"] != "admin":
        raise HTTPException(403, "Réservé à l'administrateur")


def require_tab(*tabs: str):
    """Dependency: the account has one of these tabs (an admin has them all)."""
    def check(request: Request) -> None:
        if not set(tabs) & set(require_user(request)["tabs"]):
            raise HTTPException(403, "Ce compte n'a pas accès à cette page")
    return check
