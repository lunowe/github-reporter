# app/services/user_service.py
"""
User management — GitHub App OAuth based.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.db import get_db


async def upsert_from_github(
    github_user: dict,
    access_token_encrypted: str,
    refresh_token_encrypted: str = "",
    expires_in: int = 0,
) -> dict:
    """
    Create or update a user from GitHub App OAuth data.
    Stores encrypted access + refresh tokens and the token expiry time.
    Returns the user document.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    github_id = github_user["id"]

    # Calculate expiry: GitHub App tokens expire in ~8 hours
    token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None

    update_fields: dict = {
        "github_login": github_user["login"],
        "github_avatar_url": github_user.get("avatar_url", ""),
        "github_access_token": access_token_encrypted,
        "display_name": github_user.get("name") or github_user["login"],
        "email": github_user.get("email") or "",
        "last_seen_at": now,
    }

    if refresh_token_encrypted:
        update_fields["github_refresh_token"] = refresh_token_encrypted
    if token_expires_at:
        update_fields["github_token_expires_at"] = token_expires_at

    result = await db.users.find_one_and_update(
        {"github_id": github_id},
        {
            "$set": update_fields,
            "$setOnInsert": {
                "github_id": github_id,
                "role": "user",
                "created_at": now,
            },
        },
        upsert=True,
        return_document=True,
    )

    result["id"] = str(result["_id"])
    return result


async def update_tokens(
    user_id: str,
    access_token_encrypted: str,
    refresh_token_encrypted: str,
    expires_in: int,
):
    """Update a user's GitHub tokens after a refresh."""
    db = get_db()
    now = datetime.now(timezone.utc)
    token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None

    update: dict = {
        "github_access_token": access_token_encrypted,
        "last_seen_at": now,
    }
    if refresh_token_encrypted:
        update["github_refresh_token"] = refresh_token_encrypted
    if token_expires_at:
        update["github_token_expires_at"] = token_expires_at

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update},
    )


async def get_user_by_id(user_id: str) -> dict | None:
    """Look up a user by their MongoDB ObjectId string."""
    db = get_db()
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None
    if user:
        user["id"] = str(user["_id"])
    return user


async def touch_last_seen(user_id: str):
    """Update last_seen_at timestamp."""
    db = get_db()
    try:
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"last_seen_at": datetime.now(timezone.utc)}},
        )
    except Exception:
        pass


async def ensure_indexes():
    """Create indexes for the users collection."""
    db = get_db()
    await db.users.create_index("github_id", unique=True)
