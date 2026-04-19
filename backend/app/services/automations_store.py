# app/services/automations_store.py
"""
MongoDB persistence for Automations and AutomationRuns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.db import get_db


# ── Helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_dt(dt: Any) -> Optional[str]:
    if not dt:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def serialize_automation(doc: dict) -> dict:
    return {
        "id": doc["automation_id"],
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "steps": doc.get("steps", []),
        "schedule_cron": doc.get("schedule_cron") or None,
        "timezone": doc.get("timezone", "Europe/Berlin"),
        "enabled": bool(doc.get("enabled", True)),
        "email_enabled": bool(doc.get("email_enabled", False)),
        "email_to": doc.get("email_to") or None,
        "model": doc.get("model") or None,
        "final_output_format": doc.get("final_output_format") or "last_step",
        "final_output_template": doc.get("final_output_template") or None,
        "last_run_at": _serialize_dt(doc.get("last_run_at")),
        "next_run_at": _serialize_dt(doc.get("next_run_at")),
        "created_at": _serialize_dt(doc.get("created_at")) or "",
        "updated_at": _serialize_dt(doc.get("updated_at")) or "",
    }


def serialize_run(doc: dict) -> dict:
    return {
        "id": doc["run_id"],
        "automation_id": doc.get("automation_id", ""),
        "automation_name": doc.get("automation_name", ""),
        "status": doc.get("status", "queued"),
        "trigger": doc.get("trigger", "manual"),
        "step_results": doc.get("step_results", []),
        "final_output": doc.get("final_output", ""),
        "error": doc.get("error"),
        "email_sent": bool(doc.get("email_sent", False)),
        "started_at": _serialize_dt(doc.get("started_at")) or "",
        "completed_at": _serialize_dt(doc.get("completed_at")),
    }


# ── Automations CRUD ───────────────────────────────────────────────────

async def create_automation(user_id: str, data: dict) -> dict:
    db = get_db()
    now = _now()
    doc = {
        "automation_id": str(uuid.uuid4())[:12],
        "user_id": user_id,
        "name": data["name"],
        "description": data.get("description", ""),
        "steps": [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in data.get("steps", [])],
        "schedule_cron": data.get("schedule_cron") or None,
        "timezone": data.get("timezone", "Europe/Berlin"),
        "enabled": bool(data.get("enabled", True)),
        "email_enabled": bool(data.get("email_enabled", False)),
        "email_to": data.get("email_to") or None,
        "model": data.get("model") or None,
        "final_output_format": data.get("final_output_format") or "last_step",
        "final_output_template": data.get("final_output_template") or None,
        "last_run_at": None,
        "next_run_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.automations.insert_one(doc)
    return doc


async def list_automations(user_id: str) -> list[dict]:
    db = get_db()
    cursor = db.automations.find({"user_id": user_id}).sort("created_at", -1)
    return [doc async for doc in cursor]


async def get_automation(automation_id: str, user_id: str) -> dict | None:
    db = get_db()
    return await db.automations.find_one(
        {"automation_id": automation_id, "user_id": user_id}
    )


async def get_automation_any(automation_id: str) -> dict | None:
    """Fetch without user_id filter — used by the scheduler."""
    db = get_db()
    return await db.automations.find_one({"automation_id": automation_id})


async def update_automation(
    automation_id: str, user_id: str, updates: dict
) -> dict | None:
    db = get_db()
    sanitized: dict[str, Any] = {}
    allowed = {
        "name", "description", "steps", "schedule_cron", "timezone",
        "enabled", "email_enabled", "email_to", "model",
        "final_output_format", "final_output_template",
    }
    # `final_output_template` can legitimately be cleared to None.
    nullable = {"final_output_template"}
    for k, v in updates.items():
        if k not in allowed:
            continue
        if v is None and k not in nullable:
            continue
        if k == "steps":
            sanitized[k] = [
                s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in v
            ]
        else:
            sanitized[k] = v

    if not sanitized:
        return await get_automation(automation_id, user_id)

    sanitized["updated_at"] = _now()
    result = await db.automations.find_one_and_update(
        {"automation_id": automation_id, "user_id": user_id},
        {"$set": sanitized},
        return_document=True,
    )
    return result


async def delete_automation(automation_id: str, user_id: str) -> bool:
    db = get_db()
    result = await db.automations.delete_one(
        {"automation_id": automation_id, "user_id": user_id}
    )
    # cascade-delete runs
    await db.automation_runs.delete_many({"automation_id": automation_id})
    return result.deleted_count > 0


async def list_all_enabled_automations() -> list[dict]:
    """For scheduler startup — load every enabled automation with a cron."""
    db = get_db()
    cursor = db.automations.find(
        {"enabled": True, "schedule_cron": {"$ne": None, "$exists": True}}
    )
    return [doc async for doc in cursor]


async def set_last_run(automation_id: str, when: datetime | None = None):
    db = get_db()
    await db.automations.update_one(
        {"automation_id": automation_id},
        {"$set": {"last_run_at": when or _now()}},
    )


async def set_next_run(automation_id: str, when: datetime | None):
    db = get_db()
    await db.automations.update_one(
        {"automation_id": automation_id},
        {"$set": {"next_run_at": when}},
    )


# ── Runs ────────────────────────────────────────────────────────────────

async def create_run(
    automation_id: str,
    user_id: str,
    automation_name: str,
    trigger: str = "manual",
) -> dict:
    db = get_db()
    doc = {
        "run_id": str(uuid.uuid4())[:12],
        "automation_id": automation_id,
        "user_id": user_id,
        "automation_name": automation_name,
        "status": "running",
        "trigger": trigger,
        "step_results": [],
        "final_output": "",
        "error": None,
        "email_sent": False,
        "started_at": _now(),
        "completed_at": None,
    }
    await db.automation_runs.insert_one(doc)
    return doc


async def update_run(run_id: str, updates: dict) -> dict | None:
    db = get_db()
    return await db.automation_runs.find_one_and_update(
        {"run_id": run_id},
        {"$set": updates},
        return_document=True,
    )


async def append_step_result(run_id: str, step_result: dict):
    db = get_db()
    await db.automation_runs.update_one(
        {"run_id": run_id},
        {"$push": {"step_results": step_result}},
    )


async def list_runs(automation_id: str, user_id: str, limit: int = 50) -> list[dict]:
    db = get_db()
    cursor = (
        db.automation_runs.find({"automation_id": automation_id, "user_id": user_id})
        .sort("started_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def list_recent_runs_for_user(user_id: str, limit: int = 30) -> list[dict]:
    db = get_db()
    cursor = (
        db.automation_runs.find({"user_id": user_id})
        .sort("started_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def get_run(run_id: str, user_id: str) -> dict | None:
    db = get_db()
    return await db.automation_runs.find_one({"run_id": run_id, "user_id": user_id})


# ── Indexes ────────────────────────────────────────────────────────────

async def ensure_indexes():
    db = get_db()
    await db.automations.create_index([("user_id", 1), ("created_at", -1)])
    await db.automations.create_index(
        [("automation_id", 1), ("user_id", 1)], unique=True
    )
    await db.automations.create_index([("enabled", 1)])
    await db.automation_runs.create_index(
        [("automation_id", 1), ("started_at", -1)]
    )
    await db.automation_runs.create_index([("run_id", 1)], unique=True)
    await db.automation_runs.create_index([("user_id", 1), ("started_at", -1)])
