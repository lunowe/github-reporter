# app/routes/auth.py
"""
GitHub App authentication endpoints (SPA-friendly, no redirect responses).
Uses the GitHub App user-to-server OAuth flow with token refresh.
Also supports email/password login for invited users.
"""

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_cookie,
    get_current_user,
    is_admin,
)
from app.config import Settings, get_settings
from app.services import plans, usage_service
from app.services.crypto import encrypt_token
from app.services.user_service import (
    upsert_from_github,
    get_user_by_email,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def _user_profile(user: dict, settings: Settings) -> dict:
    """Build the user profile response dict."""
    admin_flag = is_admin(user, settings)
    plan = plans.resolve_plan(user, is_admin=admin_flag, default_plan=settings.default_plan)
    budget = plans.effective_budget_usd(user, is_admin=admin_flag, default_plan=settings.default_plan)
    return {
        "id": str(user["_id"]),
        "github_id": user.get("github_id"),
        "github_login": user.get("github_login"),
        "avatar_url": user.get("github_avatar_url", ""),
        "display_name": user.get("display_name", user.get("github_login", "")),
        "email": user.get("email", ""),
        "role": user.get("role", "user"),
        "activated": user.get("activated", False),
        "auth_method": user.get("auth_method", "github"),
        "is_admin": admin_flag,
        "plan": plan.key,
        "plan_label": plan.label,
        "budget_usd": budget,
        "extra_usage_opt_in": bool(user.get("extra_usage_opt_in", False)),
    }


@router.get("/github-url")
async def github_auth_url(
    settings: Settings = Depends(get_settings),
):
    """Return the GitHub App authorize URL for the frontend to redirect to."""
    if not settings.github_app_client_id:
        raise HTTPException(
            status_code=500,
            detail="GitHub App nicht konfiguriert (GITHUB_APP_CLIENT_ID fehlt).",
        )

    state = secrets.token_urlsafe(32)
    callback_url = f"{settings.app_url}/auth/callback"

    # GitHub Apps don't use scope in the URL —
    # permissions are defined in the App settings.
    params = urlencode({
        "client_id": settings.github_app_client_id,
        "redirect_uri": callback_url,
        "state": state,
    })

    return {
        "url": f"{GITHUB_AUTHORIZE_URL}?{params}",
        "state": state,
    }


@router.post("/github/exchange")
async def github_exchange(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """
    Exchange a GitHub App OAuth code for a user access token.
    GitHub App tokens expire (~8h) and come with a refresh token (~6 months).
    Sets the session cookie and returns the user profile.
    """
    body = await request.json()
    code = body.get("code", "")

    if not code:
        raise HTTPException(status_code=400, detail="Kein Autorisierungscode erhalten.")

    callback_url = f"{settings.app_url}/auth/callback"

    # Exchange code for access token + refresh token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_app_client_id,
                "client_secret": settings.github_app_client_secret,
                "code": code,
                "redirect_uri": callback_url,
            },
            headers={"Accept": "application/json"},
        )

    if token_response.status_code != 200:
        logger.error("GitHub token exchange failed: %s", token_response.text)
        raise HTTPException(status_code=502, detail="GitHub Token-Austausch fehlgeschlagen.")

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        error_desc = token_data.get("error_description", token_data.get("error", "unknown"))
        logger.error("GitHub App OAuth error: %s", error_desc)
        raise HTTPException(status_code=400, detail=f"GitHub OAuth Fehler: {error_desc}")

    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 0)  # seconds, typically 28800 (8h)

    # Fetch GitHub user profile
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    if user_response.status_code != 200:
        raise HTTPException(status_code=502, detail="GitHub Profil konnte nicht abgerufen werden.")

    github_user = user_response.json()

    # Encrypt tokens & upsert user
    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token) if refresh_token else ""

    user = await upsert_from_github(
        github_user,
        access_token_encrypted=encrypted_access,
        refresh_token_encrypted=encrypted_refresh,
        expires_in=expires_in,
        admin_github_login=settings.admin_github_login,
        require_access_code=settings.require_access_code,
    )

    # Build JSON response with session cookie
    user_profile = _user_profile(user, settings)

    session_token = create_session_cookie(str(user["_id"]), settings)
    response = JSONResponse(content={"user": user_profile})
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )

    logger.info("User logged in via GitHub App: %s (%s)", github_user["login"], github_user["id"])
    return response


@router.post("/email/login")
async def email_login(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Email/password login for invited users."""
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="E-Mail und Passwort erforderlich.")

    user = await get_user_by_email(email)
    if not user or not verify_password(user, password):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten.")

    user_profile = _user_profile(user, settings)

    session_token = create_session_cookie(str(user["_id"]), settings)
    response = JSONResponse(content={"user": user_profile})
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )

    logger.info("User logged in via email: %s", email)
    return response


@router.post("/logout")
async def logout():
    """Clear the session cookie."""
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
async def me(
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Return the current user's profile, including this month's usage summary."""
    profile = _user_profile(user, settings)
    try:
        profile["usage"] = await usage_service.usage_summary(
            user, is_admin=profile["is_admin"], default_plan=settings.default_plan,
        )
    except Exception:
        logger.exception("Failed to attach usage summary to /me")
        profile["usage"] = None
    return profile
