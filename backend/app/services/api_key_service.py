# app/services/api_key_service.py
"""
Personal API keys — used to authenticate against the MCP server.

A key impersonates its owner: tool calls run with the owner's GitHub token and
are limited to the owner's repo permissions. Keys are shown in plaintext exactly
once (at creation) and stored only as a SHA-256 hash. Because the keys are
high-entropy random tokens, a plain SHA-256 is sufficient and — unlike bcrypt —
lets us look a key up by hash in O(1).
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone

from bson import ObjectId

from app.db import get_db
from app.services.user_service import get_user_by_id

logger = logging.getLogger(__name__)

KEY_PREFIX = "ghr_"
# Number of characters (including the prefix) shown to the user for identification.
DISPLAY_PREFIX_LEN = 12


def _hash_key(plaintext: str) -> str:
    """Stable lookup hash for a plaintext key."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _generate_key_string() -> str:
    """Generate a high-entropy key like 'ghr_<43 url-safe chars>'."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


async def generate_api_key(user_id: str, name: str) -> tuple[dict, str]:
    """
    Create a new API key for a user.

    Returns (stored_doc, plaintext). The plaintext is never persisted and must
    be surfaced to the caller immediately — it cannot be recovered later.
    """
    db = get_db()
    plaintext = _generate_key_string()
    now = datetime.now(timezone.utc)

    doc = {
        "user_id": user_id,
        "name": name.strip() or "Unbenannt",
        "key_hash": _hash_key(plaintext),
        "prefix": plaintext[:DISPLAY_PREFIX_LEN],
        "revoked": False,
        "created_at": now,
        "last_used_at": None,
    }
    result = await db.api_keys.insert_one(doc)
    doc["_id"] = result.inserted_id
    logger.info("API key created for user %s (%s…)", user_id, doc["prefix"])
    return doc, plaintext


async def authenticate_api_key(plaintext: str) -> dict | None:
    """
    Resolve a plaintext API key to its owning user document.

    Returns None if the key is unknown or revoked. Bumps last_used_at on success.
    """
    if not plaintext or not plaintext.startswith(KEY_PREFIX):
        return None

    db = get_db()
    key_doc = await db.api_keys.find_one({
        "key_hash": _hash_key(plaintext),
        "revoked": False,
    })
    if not key_doc:
        return None

    user = await get_user_by_id(key_doc["user_id"])
    if not user:
        return None

    # Best-effort usage timestamp; never block auth on it.
    await db.api_keys.update_one(
        {"_id": key_doc["_id"]},
        {"$set": {"last_used_at": datetime.now(timezone.utc)}},
    )
    return user


def _serialize(doc: dict) -> dict:
    """Public (masked) representation — never includes the hash or plaintext."""
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "prefix": doc.get("prefix", ""),
        "revoked": doc.get("revoked", False),
        "created_at": doc.get("created_at"),
        "last_used_at": doc.get("last_used_at"),
    }


async def list_keys(user_id: str) -> list[dict]:
    """List a user's API keys (masked), newest first."""
    db = get_db()
    keys: list[dict] = []
    async for doc in db.api_keys.find({"user_id": user_id}).sort("created_at", -1):
        keys.append(_serialize(doc))
    return keys


async def revoke_key(user_id: str, key_id: str) -> bool:
    """Revoke one of the user's own keys. Returns False if not found / not theirs."""
    db = get_db()
    try:
        oid = ObjectId(key_id)
    except Exception:
        return False
    result = await db.api_keys.update_one(
        {"_id": oid, "user_id": user_id},
        {"$set": {"revoked": True}},
    )
    return result.modified_count > 0


async def ensure_indexes():
    """Create indexes for the api_keys collection."""
    db = get_db()
    await db.api_keys.create_index("key_hash", unique=True)
    await db.api_keys.create_index("user_id")
