# app/services/usage_service.py
"""
Token & cost usage tracking.

``usage_events`` is an append-only log — one document per LLM run (one chat run;
one automation step). It is the source of truth; all metrics are aggregated from
it on demand. Cost is snapshotted at write time via ``pricing.compute_cost`` so
later price-table edits don't rewrite history.

Also hosts the rate-limit *decision* (``check_limit``). Enforcement is performed
by the caller only when ``settings.usage_limit_enforced`` is True — this iteration
it stays off (foundation first), so this is wired but inert.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Literal

from app.db import get_db
from app.services import pricing, plans

logger = logging.getLogger(__name__)

UsageKind = Literal["chat", "automation"]


def month_start(now: datetime | None = None) -> datetime:
    """Start of the current calendar month in UTC."""
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def ensure_indexes() -> None:
    db = get_db()
    await db.usage_events.create_index([("user_id", 1), ("created_at", -1)])
    await db.usage_events.create_index([("created_at", -1)])
    await db.usage_events.create_index([("model", 1)])


async def record_usage(
    *,
    user_id: str,
    kind: UsageKind,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int | None = None,
    cached_tokens: int = 0,
    repo: str = "",
    chat_id: str | None = None,
    automation_id: str | None = None,
    run_id: str | None = None,
    step_order: int | None = None,
    status: str = "complete",
) -> None:
    """
    Best-effort: insert one usage event. Never raises into the caller — usage
    accounting must not break a chat stream or an automation run.
    """
    try:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total = int(total_tokens) if total_tokens else prompt_tokens + completion_tokens

        # Skip truly empty runs (e.g. an immediate error before any LLM call).
        if total <= 0:
            return

        cost = pricing.compute_cost(model, prompt_tokens, completion_tokens, cached_tokens)

        doc = {
            "user_id": user_id,
            "kind": kind,
            "chat_id": chat_id,
            "automation_id": automation_id,
            "run_id": run_id,
            "step_order": step_order,
            "repo": repo,
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
            "cached_tokens": max(0, int(cached_tokens or 0)),
            "input_cost_usd": cost.input_cost_usd,
            "output_cost_usd": cost.output_cost_usd,
            "cost_usd": cost.cost_usd,
            "pricing_version": cost.pricing_version,
            "priced": cost.priced,
            "status": status,
            "created_at": datetime.now(timezone.utc),
        }
        await get_db().usage_events.insert_one(doc)
    except Exception:
        logger.exception("Failed to record usage event (user=%s kind=%s)", user_id, kind)


async def record_adjustment(
    *,
    user_id: str,
    delta_usd: float,
    note: str = "",
    admin_id: str = "",
) -> bool:
    """
    Insert a manual cost adjustment (negative ``delta_usd`` == a credit).

    Stored as a ``kind="adjustment"`` event so it nets into period/lifetime
    totals (and thus the budget) while staying out of the per-model and daily
    visual breakdowns. Keeps a full audit trail (who, when, why).
    """
    try:
        doc = {
            "user_id": user_id,
            "kind": "adjustment",
            "chat_id": None,
            "automation_id": None,
            "run_id": None,
            "step_order": None,
            "repo": "",
            "provider": "",
            "model": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cost_usd": round(float(delta_usd), 6),
            "pricing_version": pricing.PRICING_VERSION,
            "priced": True,
            "status": "adjustment",
            "note": note,
            "admin_id": admin_id,
            "created_at": datetime.now(timezone.utc),
        }
        await get_db().usage_events.insert_one(doc)
        return True
    except Exception:
        logger.exception("Failed to record usage adjustment (user=%s)", user_id)
        return False


# ── Aggregations ─────────────────────────────────────────────────────────

_TOTALS_GROUP = {
    "_id": None,
    "cost_usd": {"$sum": "$cost_usd"},
    "total_tokens": {"$sum": "$total_tokens"},
    "prompt_tokens": {"$sum": "$prompt_tokens"},
    "completion_tokens": {"$sum": "$completion_tokens"},
    "run_count": {"$sum": 1},
}

_EMPTY_TOTALS = {
    "cost_usd": 0.0,
    "total_tokens": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "run_count": 0,
}


def _clean_totals(doc: dict | None) -> dict:
    if not doc:
        return dict(_EMPTY_TOTALS)
    return {
        "cost_usd": round(doc.get("cost_usd", 0.0), 6),
        "total_tokens": int(doc.get("total_tokens", 0)),
        "prompt_tokens": int(doc.get("prompt_tokens", 0)),
        "completion_tokens": int(doc.get("completion_tokens", 0)),
        "run_count": int(doc.get("run_count", 0)),
    }


async def _totals(match: dict) -> dict:
    db = get_db()
    rows = await db.usage_events.aggregate(
        [{"$match": match}, {"$group": _TOTALS_GROUP}]
    ).to_list(length=1)
    return _clean_totals(rows[0] if rows else None)


async def period_usage(user_id: str, since: datetime) -> dict:
    return await _totals({"user_id": user_id, "created_at": {"$gte": since}})


async def lifetime_usage(user_id: str) -> dict:
    return await _totals({"user_id": user_id})


async def bulk_period_usage(user_ids: Iterable[str], since: datetime) -> dict[str, dict]:
    """Per-user totals since `since` in a single aggregation (avoids N+1)."""
    ids = list(user_ids)
    if not ids:
        return {}
    db = get_db()
    rows = await db.usage_events.aggregate([
        {"$match": {"user_id": {"$in": ids}, "created_at": {"$gte": since}}},
        {"$group": {**_TOTALS_GROUP, "_id": "$user_id", "last_activity": {"$max": "$created_at"}}},
    ]).to_list(length=None)
    out: dict[str, dict] = {}
    for r in rows:
        totals = _clean_totals(r)
        totals["last_activity"] = r.get("last_activity")
        out[r["_id"]] = totals
    return out


def build_summary(
    user: dict,
    totals: dict,
    *,
    is_admin: bool = False,
    default_plan: str = plans.FALLBACK_PLAN_KEY,
) -> dict:
    """
    Build a usage-vs-budget summary from already-fetched period totals.
    Pure (no DB) so it can be reused inside the bulk admin listing.
    """
    plan = plans.resolve_plan(user, is_admin=is_admin, default_plan=default_plan)
    budget = plans.effective_budget_usd(user, is_admin=is_admin, default_plan=default_plan)
    cost = round(totals.get("cost_usd", 0.0), 6)

    pct_used = None
    overage = 0.0
    if budget and budget > 0:
        pct_used = round(cost / budget * 100, 1)
        overage = round(max(0.0, cost - budget), 6)

    return {
        "plan": plan.key,
        "plan_label": plan.label,
        "budget_usd": budget,  # None == unlimited
        "extra_usage_opt_in": bool(user.get("extra_usage_opt_in", False)),
        "overage_allowed": plan.overage_allowed,
        "period_cost_usd": cost,
        "period_tokens": totals.get("total_tokens", 0),
        "run_count": totals.get("run_count", 0),
        "pct_used": pct_used,
        "overage_usd": overage,
        "last_activity": totals.get("last_activity"),
    }


async def usage_summary(
    user: dict,
    *,
    is_admin: bool = False,
    default_plan: str = plans.FALLBACK_PLAN_KEY,
    since: datetime | None = None,
) -> dict:
    since = since or month_start()
    totals = await period_usage(str(user["_id"]), since)
    return build_summary(user, totals, is_admin=is_admin, default_plan=default_plan)


async def per_model_breakdown(match: dict) -> list[dict]:
    db = get_db()
    rows = await db.usage_events.aggregate([
        {"$match": {**match, "kind": {"$ne": "adjustment"}}},
        {"$group": {
            "_id": {"provider": "$provider", "model": "$model"},
            "cost_usd": {"$sum": "$cost_usd"},
            "total_tokens": {"$sum": "$total_tokens"},
            "run_count": {"$sum": 1},
        }},
        {"$sort": {"cost_usd": -1}},
    ]).to_list(length=None)
    return [{
        "provider": r["_id"].get("provider", ""),
        "model": r["_id"].get("model", ""),
        "cost_usd": round(r.get("cost_usd", 0.0), 6),
        "total_tokens": int(r.get("total_tokens", 0)),
        "run_count": int(r.get("run_count", 0)),
    } for r in rows]


async def daily_series(match: dict, *, days: int = 30) -> list[dict]:
    """Daily cost/token series (UTC), oldest→newest, for the matched events."""
    db = get_db()
    rows = await db.usage_events.aggregate([
        {"$match": {**match, "kind": {"$ne": "adjustment"}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": "UTC"}},
            "cost_usd": {"$sum": "$cost_usd"},
            "total_tokens": {"$sum": "$total_tokens"},
            "run_count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]).to_list(length=None)
    return [{
        "date": r["_id"],
        "cost_usd": round(r.get("cost_usd", 0.0), 6),
        "total_tokens": int(r.get("total_tokens", 0)),
        "run_count": int(r.get("run_count", 0)),
    } for r in rows[-days:]]


async def recent_runs(user_id: str, *, limit: int = 20) -> list[dict]:
    db = get_db()
    rows = await db.usage_events.find(
        {"user_id": user_id}
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return [{
        "kind": r.get("kind", ""),
        "repo": r.get("repo", ""),
        "model": r.get("model", ""),
        "provider": r.get("provider", ""),
        "total_tokens": r.get("total_tokens", 0),
        "cost_usd": round(r.get("cost_usd", 0.0), 6),
        "status": r.get("status", ""),
        "created_at": r.get("created_at"),
    } for r in rows]


async def overview(since: datetime) -> dict:
    """Global usage overview for the admin dashboard."""
    db = get_db()
    period = await _totals({"created_at": {"$gte": since}})
    lifetime = await _totals({})

    by_model = await per_model_breakdown({"created_at": {"$gte": since}})
    series = await daily_series({"created_at": {"$gte": since}}, days=31)

    # chat vs automation split (period)
    kind_rows = await db.usage_events.aggregate([
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$kind", "cost_usd": {"$sum": "$cost_usd"}, "run_count": {"$sum": 1}}},
    ]).to_list(length=None)
    by_kind = {r["_id"]: {"cost_usd": round(r.get("cost_usd", 0.0), 6), "run_count": int(r.get("run_count", 0))} for r in kind_rows}

    # top users by cost (period)
    top_rows = await db.usage_events.aggregate([
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$user_id", "cost_usd": {"$sum": "$cost_usd"}, "total_tokens": {"$sum": "$total_tokens"}, "run_count": {"$sum": 1}}},
        {"$sort": {"cost_usd": -1}},
        {"$limit": 10},
    ]).to_list(length=10)

    return {
        "period_start": since,
        "period": period,
        "lifetime": lifetime,
        "by_model": by_model,
        "by_kind": by_kind,
        "daily_series": series,
        "top_users": top_rows,  # caller enriches with display names
    }


# ── Rate-limit decision (enforcement gated by settings) ────────────────────

async def check_limit(
    user: dict,
    *,
    is_admin: bool = False,
    default_plan: str = plans.FALLBACK_PLAN_KEY,
) -> dict:
    """
    Decide whether `user` may start another run. Pure decision — the caller
    raises 429 only when ``settings.usage_limit_enforced`` is on.

    Blocked iff: a finite budget exists, the user is over it, and they have NOT
    opted into pay-per-token overage.
    """
    budget = plans.effective_budget_usd(user, is_admin=is_admin, default_plan=default_plan)
    if budget is None:  # unlimited
        return {"allowed": True, "reason": None, "budget_usd": None}

    totals = await period_usage(str(user["_id"]), month_start())
    cost = totals.get("cost_usd", 0.0)
    over = cost >= budget
    opted_in = bool(user.get("extra_usage_opt_in", False))

    allowed = (not over) or opted_in
    return {
        "allowed": allowed,
        "reason": None if allowed else "monthly_budget_exceeded",
        "budget_usd": budget,
        "period_cost_usd": round(cost, 6),
        "extra_usage_opt_in": opted_in,
    }


async def check_run_allowed(
    user: dict,
    *,
    model: str,
    is_admin: bool = False,
    default_plan: str = plans.FALLBACK_PLAN_KEY,
    enforce_budget: bool = False,
) -> dict:
    """
    The full gate for starting a run. Returns ``{"allowed": bool, ...}`` with an
    HTTP ``status`` and a German ``message`` when blocked.

    Always-on checks: account suspension, per-user model allow-list. Budget is
    only consulted when ``enforce_budget`` is True. Admins bypass everything.
    """
    if is_admin:
        return {"allowed": True}

    if user.get("suspended"):
        return {
            "allowed": False,
            "status": 403,
            "reason": "suspended",
            "message": "Dein Konto wurde gesperrt. Bitte kontaktiere den Administrator.",
        }

    allowed_models = user.get("allowed_models") or []
    if allowed_models and model not in allowed_models:
        return {
            "allowed": False,
            "status": 403,
            "reason": "model_not_allowed",
            "message": "Dieses Modell ist für dein Konto nicht freigegeben.",
        }

    if enforce_budget:
        d = await check_limit(user, is_admin=is_admin, default_plan=default_plan)
        if not d["allowed"]:
            return {
                "allowed": False,
                "status": 429,
                "reason": d["reason"],
                "message": "Monatliches Nutzungsbudget aufgebraucht.",
                "budget_usd": d.get("budget_usd"),
                "period_cost_usd": d.get("period_cost_usd"),
            }

    return {"allowed": True}
