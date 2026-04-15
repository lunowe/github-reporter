# app/routes/invites.py
"""
Invite management endpoints.
Admin: create, list, revoke invitations.
Public: validate token, redeem invitation.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_cookie,
    get_admin_user,
    is_admin,
)
from app.config import Settings, get_settings
from app.models.api import InviteCreate, InviteRedeem
from app.services import invite_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invites", tags=["invites"])


@router.post("")
async def create_invite(
    body: InviteCreate,
    user: dict = Depends(get_admin_user),
    settings: Settings = Depends(get_settings),
):
    """Create an invitation (admin only). Returns the invite with a magic link."""
    try:
        invite = await invite_service.create_invite(
            email=body.email,
            invited_by=str(user["_id"]),
            repo_ids=body.repo_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    invite_url = f"{settings.app_url}/invite/{invite['token']}"

    return {
        "id": str(invite["_id"]),
        "email": invite["email"],
        "invite_url": invite_url,
        "repo_ids": invite.get("repo_ids", []),
        "expires_at": invite.get("expires_at", ""),
    }


@router.get("")
async def list_invites(
    user: dict = Depends(get_admin_user),
    settings: Settings = Depends(get_settings),
):
    """List all invitations (admin only)."""
    invites = await invite_service.list_invites()
    # Add invite URLs
    for inv in invites:
        inv["invite_url"] = f"{settings.app_url}/invite/{inv['token']}"
    return invites


@router.delete("/{invite_id}")
async def revoke_invite(
    invite_id: str,
    user: dict = Depends(get_admin_user),
):
    """Revoke a pending invitation (admin only)."""
    revoked = await invite_service.revoke_invite(invite_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Einladung nicht gefunden oder bereits eingelöst.")
    return {"status": "revoked"}


@router.get("/validate/{token}")
async def validate_invite(token: str):
    """Check if an invite token is valid (public endpoint)."""
    invite = await invite_service.get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Ungültige oder abgelaufene Einladung.")
    return {
        "valid": True,
        "email": invite["email"],
    }


@router.post("/redeem")
async def redeem_invite(
    body: InviteRedeem,
    settings: Settings = Depends(get_settings),
):
    """Redeem an invitation: create account and log in (public endpoint)."""
    try:
        user = await invite_service.redeem_invite(
            token=body.token,
            password=body.password,
            display_name=body.display_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Build profile response
    user_profile = {
        "id": str(user["_id"]),
        "github_id": user.get("github_id"),
        "github_login": user.get("github_login"),
        "avatar_url": user.get("github_avatar_url", ""),
        "display_name": user.get("display_name", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "viewer"),
        "activated": True,
        "auth_method": "email",
        "is_admin": is_admin(user, settings),
    }

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

    return response
