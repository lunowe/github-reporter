# app/services/access_code_service.py
"""
Access code management — generate, list, revoke, redeem codes.
"""

import logging
import secrets
from datetime import datetime, timezone

from bson import ObjectId

from app.db import get_db

logger = logging.getLogger(__name__)


def _generate_code_string() -> str:
    """Generate a readable code like XXXX-XXXX-XXXX."""
    raw = secrets.token_hex(6).upper()  # 12 hex chars
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


async def generate_code(label: str, max_uses: int, created_by: str) -> dict:
    """Create a new access code."""
    db = get_db()
    code_str = _generate_code_string()
    now = datetime.now(timezone.utc)

    doc = {
        "code": code_str,
        "label": label,
        "max_uses": max_uses,  # 0 = unlimited
        "used_count": 0,
        "used_by": [],
        "revoked": False,
        "created_at": now,
        "created_by": created_by,
    }
    result = await db.access_codes.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def list_codes() -> list[dict]:
    """List all access codes with usage stats."""
    db = get_db()
    codes = []
    async for doc in db.access_codes.find().sort("created_at", -1):
        codes.append({
            "id": str(doc["_id"]),
            "code": doc["code"],
            "label": doc.get("label", ""),
            "max_uses": doc.get("max_uses", 1),
            "used_count": doc.get("used_count", 0),
            "used_by": doc.get("used_by", []),
            "revoked": doc.get("revoked", False),
            "created_at": doc.get("created_at", ""),
        })
    return codes


async def revoke_code(code_id: str) -> bool:
    """Revoke an access code."""
    db = get_db()
    result = await db.access_codes.update_one(
        {"_id": ObjectId(code_id)},
        {"$set": {"revoked": True}},
    )
    return result.modified_count > 0


async def redeem_code(code_str: str, user: dict) -> bool:
    """
    Validate and redeem an access code for a user.
    Sets the user's activated flag to True.
    Returns True on success, raises ValueError on failure.
    """
    db = get_db()
    code_str = code_str.strip().upper()

    # Find the code
    code_doc = await db.access_codes.find_one({"code": code_str})
    if not code_doc:
        raise ValueError("Ungültiger Zugangscode.")

    if code_doc.get("revoked"):
        raise ValueError("Dieser Zugangscode wurde widerrufen.")

    max_uses = code_doc.get("max_uses", 1)
    used_count = code_doc.get("used_count", 0)
    if max_uses > 0 and used_count >= max_uses:
        raise ValueError("Dieser Zugangscode wurde bereits verwendet.")

    # Check if user already redeemed this code
    user_id = str(user["_id"])
    used_by = code_doc.get("used_by", [])
    if any(u["user_id"] == user_id for u in used_by):
        raise ValueError("Du hast diesen Code bereits verwendet.")

    now = datetime.now(timezone.utc)

    # Atomically increment usage and add user to used_by
    await db.access_codes.update_one(
        {"_id": code_doc["_id"]},
        {
            "$inc": {"used_count": 1},
            "$push": {
                "used_by": {
                    "user_id": user_id,
                    "github_login": user.get("github_login", ""),
                    "redeemed_at": now,
                },
            },
        },
    )

    # Activate the user
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "activated": True,
                "activated_via": "access_code",
                "activated_at": now,
                "access_code_used": code_str,
            },
        },
    )

    logger.info("Access code %s redeemed by %s", code_str, user.get("github_login"))
    return True


async def ensure_indexes():
    """Create indexes for the access_codes collection."""
    db = get_db()
    await db.access_codes.create_index("code", unique=True)
