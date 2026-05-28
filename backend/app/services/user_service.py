# app/services/user_service.py
"""
User management — GitHub App OAuth based, with activation & email auth support.
"""

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from bson import ObjectId

from app.db import get_db
from app.services.plans import FALLBACK_PLAN_KEY

logger = logging.getLogger(__name__)


async def upsert_from_github(
    github_user: dict,
    access_token_encrypted: str,
    refresh_token_encrypted: str = "",
    expires_in: int = 0,
    *,
    admin_github_login: str = "",
    require_access_code: bool = True,
) -> dict:
    """
    Create or update a user from GitHub App OAuth data.
    Stores encrypted access + refresh tokens and the token expiry time.
    Returns the user document.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    github_id = github_user["id"]
    github_login = github_user["login"]

    # Calculate expiry: GitHub App tokens expire in ~8 hours
    token_expires_at = now + timedelta(seconds=expires_in) if expires_in else None

    # Determine if this user should be auto-activated
    is_admin = bool(admin_github_login and github_login == admin_github_login)
    auto_activate = is_admin or not require_access_code

    update_fields: dict = {
        "github_login": github_login,
        "github_avatar_url": github_user.get("avatar_url", ""),
        "github_access_token": access_token_encrypted,
        "display_name": github_user.get("name") or github_login,
        "email": github_user.get("email") or "",
        "last_seen_at": now,
    }

    if refresh_token_encrypted:
        update_fields["github_refresh_token"] = refresh_token_encrypted
    if token_expires_at:
        update_fields["github_token_expires_at"] = token_expires_at

    # Admin is always activated
    if is_admin:
        update_fields["activated"] = True
        update_fields["activated_via"] = "admin"
        update_fields["activated_at"] = now

    set_on_insert: dict = {
        "github_id": github_id,
        "role": "user",
        "auth_method": "github",
        "created_at": now,
        "plan": FALLBACK_PLAN_KEY,
        "plan_overrides": {},
        "extra_usage_opt_in": False,
    }

    # New users: activated depends on settings
    # Skip if admin — those fields are already in $set and would conflict
    if not is_admin:
        if auto_activate:
            set_on_insert["activated"] = True
            set_on_insert["activated_via"] = "no_code_required"
            set_on_insert["activated_at"] = now
        else:
            set_on_insert["activated"] = False
            set_on_insert["activated_via"] = None
            set_on_insert["activated_at"] = None

    result = await db.users.find_one_and_update(
        {"github_id": github_id},
        {
            "$set": update_fields,
            "$setOnInsert": set_on_insert,
        },
        upsert=True,
        return_document=True,
    )

    result["id"] = str(result["_id"])
    return result


async def create_email_user(
    email: str,
    password: str,
    display_name: str,
    invited_by: str,
    proxy_github_user_id: str,
    allowed_repo_ids: list[str],
) -> dict:
    """Create a viewer user from an email invite."""
    db = get_db()
    now = datetime.now(timezone.utc)

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    doc = {
        "auth_method": "email",
        "role": "viewer",
        "email": email,
        "display_name": display_name or email.split("@")[0],
        "password_hash": password_hash,
        "proxy_github_user_id": proxy_github_user_id,
        "allowed_repo_ids": allowed_repo_ids,
        "invited_by": invited_by,
        "plan": FALLBACK_PLAN_KEY,
        "plan_overrides": {},
        "extra_usage_opt_in": False,
        "activated": True,
        "activated_via": "invite",
        "activated_at": now,
        "created_at": now,
        "last_seen_at": now,
        # GitHub fields intentionally omitted for email users so that the
        # sparse unique index on github_id skips these documents.
    }

    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    doc["id"] = str(result.inserted_id)
    return doc


async def get_user_by_email(email: str) -> dict | None:
    """Look up an email-auth user by their email address."""
    db = get_db()
    user = await db.users.find_one({"email": email, "auth_method": "email"})
    if user:
        user["id"] = str(user["_id"])
    return user


def verify_password(user: dict, password: str) -> bool:
    """Verify a password against the stored bcrypt hash."""
    stored_hash = user.get("password_hash", "")
    if not stored_hash:
        return False
    return bcrypt.checkpw(
        password.encode("utf-8"),
        stored_hash.encode("utf-8"),
    )


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


async def list_all_users() -> list[dict]:
    """List all users (admin view)."""
    db = get_db()
    users = []
    async for user in db.users.find().sort("created_at", -1):
        users.append({
            "id": str(user["_id"]),
            "display_name": user.get("display_name", ""),
            "github_login": user.get("github_login"),
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
            "auth_method": user.get("auth_method", "github"),
            "activated": user.get("activated", False),
            "allowed_repo_ids": user.get("allowed_repo_ids", []),
            "plan": user.get("plan", FALLBACK_PLAN_KEY),
            "plan_overrides": user.get("plan_overrides", {}),
            "extra_usage_opt_in": user.get("extra_usage_opt_in", False),
            "invited_by": user.get("invited_by"),
            "created_at": user.get("created_at", ""),
            "last_seen_at": user.get("last_seen_at", ""),
        })
    return users


async def names_for_ids(user_ids: list[str]) -> dict[str, dict]:
    """Light profile lookup (display name / login / role) for a batch of ids."""
    if not user_ids:
        return {}
    oids = []
    for i in user_ids:
        try:
            oids.append(ObjectId(i))
        except Exception:
            pass
    db = get_db()
    out: dict[str, dict] = {}
    async for u in db.users.find(
        {"_id": {"$in": oids}},
        {"display_name": 1, "github_login": 1, "email": 1, "role": 1},
    ):
        out[str(u["_id"])] = {
            "display_name": u.get("display_name", ""),
            "github_login": u.get("github_login"),
            "email": u.get("email", ""),
            "role": u.get("role", ""),
        }
    return out


async def count_invited_by(user_ids: list[str]) -> dict[str, int]:
    """How many users each of `user_ids` invited (keyed by inviter id)."""
    if not user_ids:
        return {}
    db = get_db()
    rows = await db.users.aggregate([
        {"$match": {"invited_by": {"$in": user_ids}}},
        {"$group": {"_id": "$invited_by", "count": {"$sum": 1}}},
    ]).to_list(length=None)
    return {r["_id"]: int(r["count"]) for r in rows if r.get("_id")}


async def list_invitees(inviter_id: str) -> list[dict]:
    """Users invited by `inviter_id` (light projection for the admin detail view)."""
    db = get_db()
    out = []
    async for u in db.users.find({"invited_by": inviter_id}).sort("created_at", -1):
        out.append({
            "id": str(u["_id"]),
            "display_name": u.get("display_name", ""),
            "email": u.get("email", ""),
            "role": u.get("role", "viewer"),
            "created_at": u.get("created_at", ""),
            "last_seen_at": u.get("last_seen_at", ""),
        })
    return out


async def set_user_plan(
    user_id: str,
    *,
    plan: str,
    monthly_budget_usd: float | None,
    extra_usage_opt_in: bool,
) -> dict | None:
    """Admin action: assign a plan tier, optional budget override, and overage opt-in."""
    db = get_db()
    update: dict = {"$set": {"plan": plan, "extra_usage_opt_in": bool(extra_usage_opt_in)}}
    if monthly_budget_usd is None:
        update["$unset"] = {"plan_overrides.monthly_budget_usd": ""}
    else:
        update["$set"]["plan_overrides.monthly_budget_usd"] = float(monthly_budget_usd)
    try:
        result = await db.users.find_one_and_update(
            {"_id": ObjectId(user_id)}, update, return_document=True,
        )
    except Exception:
        return None
    if result:
        result["id"] = str(result["_id"])
    return result


async def update_allowed_repos(user_id: str, allowed_repo_ids: list[str]) -> dict | None:
    """Update the allowed_repo_ids for a viewer user (admin action)."""
    db = get_db()
    try:
        result = await db.users.find_one_and_update(
            {"_id": ObjectId(user_id), "role": "viewer"},
            {"$set": {"allowed_repo_ids": allowed_repo_ids}},
            return_document=True,
        )
    except Exception:
        return None
    if result:
        result["id"] = str(result["_id"])
    return result


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


async def migrate_existing_users():
    """
    One-time migration: ensure all existing users have the new activation fields.
    Existing users are grandfathered in as activated.
    """
    db = get_db()
    result = await db.users.update_many(
        {"activated": {"$exists": False}},
        {
            "$set": {
                "activated": True,
                "auth_method": "github",
                "activated_via": "migration",
                "activated_at": datetime.now(timezone.utc),
            },
        },
    )
    if result.modified_count > 0:
        logger.info("Migrated %d existing users (set activated=True)", result.modified_count)

    # Backfill plan fields for productization (default tier + no overage).
    plan_result = await db.users.update_many(
        {"plan": {"$exists": False}},
        {"$set": {"plan": FALLBACK_PLAN_KEY, "plan_overrides": {}, "extra_usage_opt_in": False}},
    )
    if plan_result.modified_count > 0:
        logger.info("Backfilled plan fields on %d existing users", plan_result.modified_count)


async def ensure_indexes():
    """Create indexes for the users collection."""
    db = get_db()

    # The original index was unique but not sparse. Email users have github_id=None,
    # so we need sparse=True to allow multiple nulls.
    # NOTE: create_index is idempotent by *name* — if github_id_1 already exists
    # (even without sparse), it silently returns without updating options.
    # We must check the existing index and drop it if it lacks sparse=True.
    existing = await db.users.index_information()
    gh_index = existing.get("github_id_1")
    if gh_index and not gh_index.get("sparse", False):
        logger.info("Dropping non-sparse github_id index and recreating with sparse=True")
        await db.users.drop_index("github_id_1")
        await db.users.create_index("github_id", unique=True, sparse=True)
    elif not gh_index:
        await db.users.create_index("github_id", unique=True, sparse=True)

    await db.users.create_index("email", sparse=True)
