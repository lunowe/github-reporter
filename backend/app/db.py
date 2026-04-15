# app/db.py
"""
MongoDB connection — async via motor.
Single client instance, accessed globally.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def init_db(mongodb_url: str, db_name: str):
    """Call once at startup to initialise the connection."""
    global _client, _db
    _client = AsyncIOMotorClient(mongodb_url)
    _db = _client[db_name]


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _db
