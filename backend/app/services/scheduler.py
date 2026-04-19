# app/services/scheduler.py
"""
APScheduler-based cron runner for Automations.

One AsyncIOScheduler instance per process. Jobs are registered/unregistered
when automations are created, updated, toggled, or deleted.

In-process only — if you scale to multiple backend replicas, you'll want to
either pin the scheduler to one replica or move to a distributed queue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

from app.config import get_settings
from app.services import automations_store
from app.services.automation_runner import execute_automation_by_id

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def _job_id(automation_id: str) -> str:
    return f"automation:{automation_id}"


def validate_cron(expr: str) -> bool:
    """Return True if `expr` is a valid 5-field cron expression."""
    if not expr or not expr.strip():
        return False
    try:
        croniter(expr)
        return True
    except (ValueError, KeyError):
        return False


_DOW_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _convert_dow_field(field: str) -> str:
    """
    Convert a cron day-of-week field from standard convention (0/7=Sun, 1=Mon)
    to APScheduler convention (0=Mon, …, 6=Sun) by replacing numeric tokens
    with day-name abbreviations. Non-numeric tokens pass through unchanged.
    """
    if field == "*" or field == "?":
        return field

    def _to_name(num_str: str) -> str:
        n = int(num_str)
        if n == 7:
            n = 0
        if not 0 <= n <= 6:
            raise ValueError(f"Ungültiger Wochentag: {num_str}")
        # Standard cron: 0=Sun, 1=Mon, ..., 6=Sat
        # APScheduler names: mon=0..sun=6
        # Mapping: cron 0 → sun; cron 1 → mon; …; cron 6 → sat
        return _DOW_NAMES[(n - 1) % 7]

    def _convert_token(token: str) -> str:
        # Handle step values like "*/2" or "1-5/2"
        if "/" in token:
            base, step = token.split("/", 1)
            return f"{_convert_token(base)}/{step}"
        # Handle ranges like "1-5"
        if "-" in token:
            a, b = token.split("-", 1)
            return f"{_to_name(a)}-{_to_name(b)}"
        # Bare number
        if token.isdigit():
            return _to_name(token)
        # Already a name or wildcard
        return token

    return ",".join(_convert_token(t) for t in field.split(","))


def _parse_cron_trigger(cron_expr: str, tz: str) -> CronTrigger:
    """
    Parse a standard 5-field cron expression into an APScheduler CronTrigger.

    APScheduler uses Monday=0 for day-of-week, but standard cron uses
    Sunday=0/7. We convert the day-of-week field to day-name abbreviations
    so the trigger fires on the days the user actually expects.
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron muss 5 Felder haben, bekam {len(parts)}: {cron_expr!r}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=_convert_dow_field(day_of_week),
        timezone=tz,
    )


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


async def start_scheduler():
    """Start the scheduler and load all enabled automations from DB."""
    global _scheduler
    settings = get_settings()

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via config — skipping startup")
        return

    if _scheduler is not None:
        logger.warning("Scheduler already started")
        return

    _scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
    _scheduler.start()
    logger.info("APScheduler started (tz=%s)", settings.scheduler_timezone)

    # Register all enabled automations with valid cron expressions
    automations = await automations_store.list_all_enabled_automations()
    registered = 0
    for auto in automations:
        cron = auto.get("schedule_cron")
        if not cron:
            continue
        try:
            _register_job(auto)
            registered += 1
        except Exception:
            logger.exception(
                "Failed to register automation %s on startup",
                auto.get("automation_id"),
            )
    logger.info("Registered %d scheduled automations", registered)


async def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped")


def _register_job(automation: dict):
    """Add or replace a job for `automation` in the running scheduler."""
    if _scheduler is None:
        return

    automation_id = automation["automation_id"]
    cron = automation.get("schedule_cron")
    tz = automation.get("timezone") or get_settings().scheduler_timezone

    if not cron:
        return

    trigger = _parse_cron_trigger(cron, tz)
    _scheduler.add_job(
        execute_automation_by_id,
        trigger=trigger,
        args=[automation_id, "schedule"],
        id=_job_id(automation_id),
        replace_existing=True,
        misfire_grace_time=60 * 30,  # 30 min — if we missed the window, still run
        coalesce=True,  # collapse backed-up runs into one
        max_instances=1,  # no overlapping runs for the same automation
    )
    logger.info("Registered job for automation %s (cron=%r tz=%s)", automation_id, cron, tz)


def _unregister_job(automation_id: str):
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_job_id(automation_id))
        logger.info("Unregistered job for automation %s", automation_id)
    except Exception:
        pass  # job not registered — ignore


async def sync_automation(automation: dict):
    """
    Ensure the scheduler state matches the DB state for this automation.
    Call after create/update/toggle. Also updates next_run_at in DB.
    """
    automation_id = automation["automation_id"]
    enabled = automation.get("enabled", True)
    cron = automation.get("schedule_cron")

    if enabled and cron and validate_cron(cron):
        _register_job(automation)
        # Compute next fire time for UI
        try:
            tz = automation.get("timezone") or get_settings().scheduler_timezone
            trigger = _parse_cron_trigger(cron, tz)
            next_fire = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
            await automations_store.set_next_run(automation_id, next_fire)
        except Exception:
            logger.exception("Failed to compute next_run_at for %s", automation_id)
    else:
        _unregister_job(automation_id)
        await automations_store.set_next_run(automation_id, None)


async def remove_automation(automation_id: str):
    _unregister_job(automation_id)
