# app/routes/automations.py
"""
Automations REST API — define, schedule, and run chained-prompt workflows.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_activated_user
from app.db import get_db
from app.models.api import (
    AutomationCreate,
    AutomationUpdate,
    AutomationToggle,
)
from app.services import automations_store, scheduler as scheduler_service
from app.services import email_service
from app.services.automation_runner import execute_automation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automations", tags=["automations"])


# ── Helpers ────────────────────────────────────────────────────────────

async def _user_repos(user: dict) -> set[str]:
    """Resolve the set of repo_full_names this user may target."""
    db = get_db()
    if user.get("auth_method") == "email":
        allowed_ids = user.get("allowed_repo_ids", [])
        if not allowed_ids:
            return set()
        proxy_user_id = user.get("proxy_github_user_id", "")
        query = {"user_id": proxy_user_id, "repo_id": {"$in": allowed_ids}}
    else:
        query = {"user_id": str(user["_id"])}

    repos: set[str] = set()
    async for doc in db.repos.find(query, {"repo_full_name": 1}):
        repos.add(doc["repo_full_name"])
    return repos


def _validate_cron_or_raise(cron: str | None):
    if cron is None or cron == "":
        return
    if not scheduler_service.validate_cron(cron):
        raise HTTPException(
            status_code=422,
            detail=f"Ungültiger Cron-Ausdruck: {cron!r}. Erwartet 5 Felder (Min Std Tag Monat Wochentag).",
        )


def _validate_steps_or_raise(steps: list, allowed_repos: set[str]):
    if not steps:
        raise HTTPException(status_code=422, detail="Mindestens ein Schritt erforderlich.")
    for i, step in enumerate(steps, start=1):
        repo = step.repo if hasattr(step, "repo") else step.get("repo")
        if not repo:
            raise HTTPException(status_code=422, detail=f"Schritt {i}: Repository fehlt.")
        if repo not in allowed_repos:
            raise HTTPException(
                status_code=403,
                detail=f"Schritt {i}: Kein Zugriff auf Repository {repo!r}.",
            )


# ── CRUD ───────────────────────────────────────────────────────────────

@router.get("")
async def list_my_automations(user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])
    docs = await automations_store.list_automations(user_id)
    return [automations_store.serialize_automation(d) for d in docs]


@router.post("")
async def create_automation(
    body: AutomationCreate,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    allowed = await _user_repos(user)
    _validate_steps_or_raise(body.steps, allowed)
    _validate_cron_or_raise(body.schedule_cron)

    doc = await automations_store.create_automation(user_id, body.model_dump())
    # Register in scheduler (no-op if no cron or disabled)
    await scheduler_service.sync_automation(doc)
    # Re-fetch to pick up next_run_at populated by sync
    doc = await automations_store.get_automation(doc["automation_id"], user_id)
    return automations_store.serialize_automation(doc)


@router.get("/{automation_id}")
async def get_my_automation(
    automation_id: str,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    doc = await automations_store.get_automation(automation_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")
    return automations_store.serialize_automation(doc)


@router.put("/{automation_id}")
async def update_my_automation(
    automation_id: str,
    body: AutomationUpdate,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    existing = await automations_store.get_automation(automation_id, user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")

    updates = body.model_dump(exclude_unset=True)

    if "steps" in updates and updates["steps"] is not None:
        allowed = await _user_repos(user)
        _validate_steps_or_raise(body.steps, allowed)

    if "schedule_cron" in updates:
        _validate_cron_or_raise(updates.get("schedule_cron"))

    doc = await automations_store.update_automation(automation_id, user_id, updates)
    if not doc:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")

    await scheduler_service.sync_automation(doc)
    doc = await automations_store.get_automation(automation_id, user_id)
    return automations_store.serialize_automation(doc)


@router.patch("/{automation_id}/toggle")
async def toggle_my_automation(
    automation_id: str,
    body: AutomationToggle,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    doc = await automations_store.update_automation(
        automation_id, user_id, {"enabled": body.enabled}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")
    await scheduler_service.sync_automation(doc)
    doc = await automations_store.get_automation(automation_id, user_id)
    return automations_store.serialize_automation(doc)


@router.delete("/{automation_id}")
async def delete_my_automation(
    automation_id: str,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    ok = await automations_store.delete_automation(automation_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")
    await scheduler_service.remove_automation(automation_id)
    return {"status": "deleted"}


# ── Runs ───────────────────────────────────────────────────────────────

@router.post("/{automation_id}/run")
async def run_now(
    automation_id: str,
    user: dict = Depends(get_activated_user),
):
    """Fire the automation immediately; returns the run_id for polling."""
    user_id = str(user["_id"])
    automation = await automations_store.get_automation(automation_id, user_id)
    if not automation:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")

    run = await automations_store.create_run(
        automation_id=automation_id,
        user_id=user_id,
        automation_name=automation.get("name", ""),
        trigger="manual",
    )
    run_id = run["run_id"]

    # Execute in the background so we can return immediately
    async def _bg():
        try:
            await execute_automation(automation, trigger="manual", run_id=run_id)
        except Exception:
            logger.exception("Background automation run failed: %s", run_id)

    asyncio.create_task(_bg())

    return automations_store.serialize_run(run)


@router.get("/{automation_id}/runs")
async def list_automation_runs(
    automation_id: str,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    # verify ownership
    automation = await automations_store.get_automation(automation_id, user_id)
    if not automation:
        raise HTTPException(status_code=404, detail="Automation nicht gefunden.")
    runs = await automations_store.list_runs(automation_id, user_id)
    return [automations_store.serialize_run(r) for r in runs]


@router.get("/{automation_id}/runs/{run_id}")
async def get_automation_run(
    automation_id: str,
    run_id: str,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])
    run = await automations_store.get_run(run_id, user_id)
    if not run or run.get("automation_id") != automation_id:
        raise HTTPException(status_code=404, detail="Run nicht gefunden.")
    return automations_store.serialize_run(run)


# ── Meta ───────────────────────────────────────────────────────────────

@router.get("/meta/email-status")
async def email_status(user: dict = Depends(get_activated_user)):
    """Tell the frontend whether email notifications can be delivered."""
    return {
        "configured": email_service.is_configured(),
        "default_to": user.get("email") or "",
    }
