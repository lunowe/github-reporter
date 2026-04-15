# app/auth.py
"""
Session-based authentication via signed HttpOnly cookies.
Provides FastAPI dependencies for different access levels:
  - get_current_user:   valid session (may not be activated)
  - get_activated_user: session + activated account
  - get_admin_user:     session + admin role
  - get_github_user:    session + activated + GitHub auth method
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


def is_admin(user: dict, settings: Settings) -> bool:
    """Check if a user is the configured admin."""
    admin_login = settings.admin_github_login
    if not admin_login:
        return False
    return user.get("github_login") == admin_login


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


async def get_activated_user(
    user: dict = Depends(get_current_user),
) -> dict:
    """Only allow users whose account has been activated (code redeemed or admin)."""
    if not user.get("activated", False):
        raise HTTPException(status_code=403, detail="activation_required")
    return user


async def get_admin_user(
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Only allow the configured admin user."""
    if not is_admin(user, settings):
        raise HTTPException(status_code=403, detail="Nur Administratoren.")
    return user


async def get_github_user(
    user: dict = Depends(get_activated_user),
) -> dict:
    """Only allow activated users with GitHub auth (have their own GitHub token)."""
    if user.get("auth_method", "github") != "github":
        raise HTTPException(status_code=403, detail="GitHub-Konto erforderlich.")
    return user
