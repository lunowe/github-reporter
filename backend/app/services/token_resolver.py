# app/services/token_resolver.py
"""
Resolve the GitHub access token for a given user.
Auto-refreshes expired GitHub App tokens using the refresh token.
For email/viewer users, proxies through the invitor's GitHub token.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException

from app.config import get_settings
from app.services.crypto import decrypt_token, encrypt_token
from app.services.user_service import update_tokens, get_user_by_id

logger = logging.getLogger(__name__)

GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

# Refresh 5 minutes before actual expiry to avoid race conditions
REFRESH_BUFFER_SECONDS = 300


async def resolve_github_token(user: dict) -> str:
    """
    Decrypt and return the GitHub access token for the user.
    - GitHub users: use their own token (auto-refreshed if expired).
    - Email/viewer users: proxy through the invitor's token.
    """
    # Email users proxy through the invitor's GitHub token
    if user.get("auth_method") == "email":
        proxy_user_id = user.get("proxy_github_user_id")
        if not proxy_user_id:
            raise HTTPException(
                status_code=403,
                detail="Kein verknüpfter GitHub-Benutzer. Bitte den Administrator kontaktieren.",
            )
        proxy_user = await get_user_by_id(proxy_user_id)
        if not proxy_user:
            raise HTTPException(
                status_code=403,
                detail="Verknüpfter GitHub-Benutzer nicht gefunden.",
            )
        logger.info(
            "Resolving proxy GitHub token for viewer %s via %s",
            user.get("email"),
            proxy_user.get("github_login"),
        )
        return await _resolve_token_for_github_user(proxy_user)

    return await _resolve_token_for_github_user(user)


async def _resolve_token_for_github_user(user: dict) -> str:
    """Resolve token for a GitHub-authenticated user (with auto-refresh)."""
    encrypted_access = user.get("github_access_token")
    if not encrypted_access:
        raise HTTPException(
            status_code=401,
            detail="Kein GitHub-Token vorhanden. Bitte erneut anmelden.",
        )

    # Check if token is expired (GitHub App tokens have expiry)
    expires_at = user.get("github_token_expires_at")
    if expires_at and _is_expired(expires_at):
        logger.info("GitHub token expired for user %s, refreshing...", user.get("github_login"))
        return await _refresh_token(user)

    try:
        return decrypt_token(encrypted_access)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="GitHub-Token ungültig. Bitte erneut anmelden.",
        )


def _is_expired(expires_at: datetime) -> bool:
    """Check if a token expiry time has passed (with buffer)."""
    now = datetime.now(timezone.utc)
    # Make expires_at timezone-aware if it isn't already
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now >= expires_at - timedelta(seconds=REFRESH_BUFFER_SECONDS)


async def _refresh_token(user: dict) -> str:
    """Refresh an expired GitHub App user token."""
    encrypted_refresh = user.get("github_refresh_token")
    if not encrypted_refresh:
        raise HTTPException(
            status_code=401,
            detail="Kein Refresh-Token vorhanden. Bitte erneut anmelden.",
        )

    try:
        refresh_token = decrypt_token(encrypted_refresh)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Refresh-Token ungültig. Bitte erneut anmelden.",
        )

    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_app_client_id,
                "client_secret": settings.github_app_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code != 200:
        logger.error("GitHub token refresh failed: %s", response.text)
        raise HTTPException(
            status_code=401,
            detail="Token-Aktualisierung fehlgeschlagen. Bitte erneut anmelden.",
        )

    data = response.json()
    new_access = data.get("access_token")
    if not new_access:
        error_desc = data.get("error_description", data.get("error", "unknown"))
        logger.error("GitHub refresh error: %s", error_desc)
        raise HTTPException(
            status_code=401,
            detail="Token-Aktualisierung fehlgeschlagen. Bitte erneut anmelden.",
        )

    new_refresh = data.get("refresh_token", "")
    expires_in = data.get("expires_in", 0)

    # Persist the new tokens
    user_id = str(user["_id"])
    await update_tokens(
        user_id=user_id,
        access_token_encrypted=encrypt_token(new_access),
        refresh_token_encrypted=encrypt_token(new_refresh) if new_refresh else "",
        expires_in=expires_in,
    )

    logger.info("Token refreshed for user %s", user.get("github_login"))
    return new_access
