# app/auth.py
"""
Session-based authentication via signed HttpOnly cookies.
"""

import logging

from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config import Settings, get_settings
from app.services.user_service import get_user_by_id, touch_last_seen

logger = logging.getLogger(__name__)

SESSION_COOKIE = "ghr_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


def _get_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="ghr-session")


def create_session_cookie(user_id: str, settings: Settings) -> str:
    """Create a signed session token containing the user's MongoDB _id."""
    s = _get_serializer(settings)
    return s.dumps(user_id)


def verify_session_cookie(token: str, settings: Settings) -> str | None:
    """Verify and decode a session token. Returns user_id or None."""
    s = _get_serializer(settings)
    try:
        user_id = s.loads(token, max_age=SESSION_MAX_AGE)
        return user_id
    except (BadSignature, SignatureExpired):
        return None


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Resolve session cookie → user document."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    user_id = verify_session_cookie(token, settings)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sitzung abgelaufen.")

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden.")

    # Fire-and-forget last_seen update
    await touch_last_seen(user_id)
    return user
