"""Single admin password, signed session cookie."""
import hmac

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import settings

COOKIE = "wolfy_session"
_signer = TimestampSigner(settings.secret_key(), salt="wolfy-session")


def check_password(password: str) -> bool:
    if not settings.ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())


def open_session(response: Response) -> None:
    token = _signer.sign(b"admin").decode()
    response.set_cookie(
        COOKIE, token, max_age=settings.SESSION_HOURS * 3600,
        httponly=True, samesite="strict",
    )


def close_session(response: Response) -> None:
    response.delete_cookie(COOKIE)


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    try:
        _signer.unsign(token, max_age=settings.SESSION_HOURS * 3600)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_admin(request: Request) -> None:
    if not is_logged_in(request):
        raise HTTPException(401, "Non connecté")
