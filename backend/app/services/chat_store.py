# app/services/chat_store.py
"""
Chat persistence — save and load conversations.
"""

import uuid
from datetime import datetime, timezone

from app.db import get_db


async def create_chat(user_id: str, repo: str, title: str = "") -> dict:
    """Create a new chat session."""
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "chat_id": str(uuid.uuid4())[:12],
        "user_id": user_id,
        "repo": repo,
        "title": title or "Neuer Chat",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    await db.chats.insert_one(doc)
    return doc


async def append_messages(chat_id: str, user_id: str, messages: list[dict]):
    """Append messages to an existing chat."""
    db = get_db()
    await db.chats.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {
            "$push": {"messages": {"$each": messages}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )


async def update_chat_title(chat_id: str, user_id: str, title: str):
    db = get_db()
    await db.chats.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"title": title, "updated_at": datetime.now(timezone.utc)}},
    )


async def get_chat(chat_id: str, user_id: str) -> dict | None:
    db = get_db()
    doc = await db.chats.find_one(
        {"chat_id": chat_id, "user_id": user_id},
    )
    return doc


async def list_chats(user_id: str, limit: int = 50) -> list[dict]:
    """List recent chats for a user (without full message history)."""
    db = get_db()
    cursor = db.chats.find(
        {"user_id": user_id},
        {"messages": 0},  # exclude messages for listing
    ).sort("updated_at", -1).limit(limit)
    return [doc async for doc in cursor]


async def delete_chat(chat_id: str, user_id: str) -> bool:
    db = get_db()
    result = await db.chats.delete_one({"chat_id": chat_id, "user_id": user_id})
    return result.deleted_count > 0


async def ensure_indexes():
    db = get_db()
    await db.chats.create_index([("user_id", 1), ("updated_at", -1)])
    await db.chats.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
