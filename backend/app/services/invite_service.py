# app/services/invite_service.py
"""
Invite management — create, validate, redeem invitations for non-GitHub users.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.db import get_db
from app.services.user_service import create_email_user, get_user_by_email

logger = logging.getLogger(__name__)

INVITE_EXPIRY_DAYS = 7


async def create_invite(email: str, invited_by: str, repo_ids: list[str]) -> dict:
    """Create a new invitation."""
    db = get_db()
    email = email.strip().lower()
    now = datetime.now(timezone.utc)

    # Check if email already has an account
    existing_user = await get_user_by_email(email)
    if existing_user:
        raise ValueError("Ein Benutzer mit dieser E-Mail existiert bereits.")

    # Check for existing pending invite
    existing_invite = await db.invites.find_one({
        "email": email,
        "redeemed": False,
        "expires_at": {"$gt": now},
    })
    if existing_invite:
        raise ValueError("Es gibt bereits eine ausstehende Einladung für diese E-Mail.")

    token = secrets.token_urlsafe(32)
    doc = {
        "email": email,
        "token": token,
        "invited_by": invited_by,
        "repo_ids": repo_ids,
        "created_at": now,
        "expires_at": now + timedelta(days=INVITE_EXPIRY_DAYS),
        "redeemed": False,
        "redeemed_at": None,
    }
    result = await db.invites.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_invite_by_token(token: str) -> dict | None:
    """Look up an invite by token. Returns None if expired or redeemed."""
    db = get_db()
    now = datetime.now(timezone.utc)
    invite = await db.invites.find_one({
        "token": token,
        "redeemed": False,
        "expires_at": {"$gt": now},
    })
    if invite:
        invite["id"] = str(invite["_id"])
    return invite


async def redeem_invite(token: str, password: str, display_name: str = "") -> dict:
    """
    Redeem an invitation: create a viewer user account and mark invite as used.
    Returns the created user document.
    """
    invite = await get_invite_by_token(token)
    if not invite:
        raise ValueError("Ungültige oder abgelaufene Einladung.")

    now = datetime.now(timezone.utc)

    # Create the email user
    user = await create_email_user(
        email=invite["email"],
        password=password,
        display_name=display_name or invite["email"].split("@")[0],
        invited_by=invite["invited_by"],
        proxy_github_user_id=invite["invited_by"],
        allowed_repo_ids=invite.get("repo_ids", []),
    )

    # Mark invite as redeemed
    db = get_db()
    await db.invites.update_one(
        {"_id": invite["_id"]},
        {"$set": {"redeemed": True, "redeemed_at": now}},
    )

    logger.info("Invite redeemed by %s (invited by %s)", invite["email"], invite["invited_by"])
    return user


async def list_invites() -> list[dict]:
    """List all invites (admin view)."""
    db = get_db()
    invites = []
    async for doc in db.invites.find().sort("created_at", -1):
        invites.append({
            "id": str(doc["_id"]),
            "email": doc["email"],
            "token": doc["token"],
            "invited_by": doc.get("invited_by", ""),
            "repo_ids": doc.get("repo_ids", []),
            "created_at": doc.get("created_at", ""),
            "expires_at": doc.get("expires_at", ""),
            "redeemed": doc.get("redeemed", False),
            "redeemed_at": doc.get("redeemed_at"),
        })
    return invites


async def revoke_invite(invite_id: str) -> bool:
    """Delete a pending invitation."""
    db = get_db()
    result = await db.invites.delete_one({
        "_id": ObjectId(invite_id),
        "redeemed": False,
    })
    return result.deleted_count > 0


async def ensure_indexes():
    """Create indexes for the invites collection."""
    db = get_db()
    await db.invites.create_index("token", unique=True)
    await db.invites.create_index("email")
