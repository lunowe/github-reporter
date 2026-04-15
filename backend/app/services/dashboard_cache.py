# app/services/dashboard_cache.py
"""
Dashboard cache — stores repo summaries in MongoDB with a TTL.
Avoids hitting GitHub API on every dashboard load.
"""

from datetime import datetime, timezone, timedelta

from app.db import get_db

CACHE_TTL = timedelta(minutes=5)


async def get_cached_summary(repo: str) -> dict | None:
    """Return cached summary if fresh, else None."""
    db = get_db()
    doc = await db.dashboard_cache.find_one({"repo": repo})
    if not doc:
        return None

    cached_at = doc["cached_at"]
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - cached_at
    if age > CACHE_TTL:
        return None

    return doc["summary"]


async def set_cached_summary(repo: str, summary: dict):
    """Store or update the cached summary."""
    db = get_db()
    await db.dashboard_cache.update_one(
        {"repo": repo},
        {
            "$set": {
                "summary": summary,
                "cached_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


async def ensure_indexes():
    db = get_db()
    await db.dashboard_cache.create_index("repo", unique=True)
