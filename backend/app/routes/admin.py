# app/routes/admin.py
"""
Admin-only endpoints — user management plus usage / cost insights.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_admin_user, is_admin
from app.config import Settings, get_settings
from app.models.api import UserReposUpdate, UserPlanUpdate
from app.services import plans, usage_service, user_service
from app.services.user_service import (
    list_all_users,
    update_allowed_repos,
    count_invited_by,
    list_invitees,
    names_for_ids,
    set_user_plan,
    get_user_by_id,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    user: dict = Depends(get_admin_user),
    settings: Settings = Depends(get_settings),
):
    """List all users enriched with plan, invitee count, and period usage."""
    users = await list_all_users()
    user_ids = [u["id"] for u in users]

    since = usage_service.month_start()
    bulk = await usage_service.bulk_period_usage(user_ids, since)
    invited_counts = await count_invited_by(user_ids)

    # Map inviter id → display name (inviter is normally in this same list).
    display_map = {u["id"]: u["display_name"] or u.get("github_login") or u["email"] for u in users}

    for u in users:
        totals = bulk.get(u["id"], {})
        u["usage"] = usage_service.build_summary(
            u, totals, is_admin=is_admin(u, settings), default_plan=settings.default_plan,
        )
        u["invited_count"] = invited_counts.get(u["id"], 0)
        inv = u.get("invited_by")
        u["invited_by_display"] = display_map.get(inv) if inv else None

    return users


@router.get("/users/{user_id}")
async def user_detail(
    user_id: str,
    user: dict = Depends(get_admin_user),
    settings: Settings = Depends(get_settings),
):
    """Full usage breakdown for a single user (admin only)."""
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    admin_flag = is_admin(target, settings)
    since = usage_service.month_start()

    period_totals = await usage_service.period_usage(user_id, since)
    lifetime_totals = await usage_service.lifetime_usage(user_id)
    summary = usage_service.build_summary(
        target, period_totals, is_admin=admin_flag, default_plan=settings.default_plan,
    )

    by_model = await usage_service.per_model_breakdown(
        {"user_id": user_id, "created_at": {"$gte": since}}
    )
    series = await usage_service.daily_series({"user_id": user_id}, days=30)
    recent = await usage_service.recent_runs(user_id, limit=20)

    invitees = await list_invitees(user_id)
    if invitees:
        inv_usage = await usage_service.bulk_period_usage([i["id"] for i in invitees], since)
        for i in invitees:
            t = inv_usage.get(i["id"], {})
            i["period_cost_usd"] = round(t.get("cost_usd", 0.0), 6)
            i["period_tokens"] = t.get("total_tokens", 0)

    return {
        "id": str(target["_id"]),
        "display_name": target.get("display_name", ""),
        "github_login": target.get("github_login"),
        "email": target.get("email", ""),
        "role": target.get("role", "user"),
        "auth_method": target.get("auth_method", "github"),
        "activated": target.get("activated", False),
        "created_at": target.get("created_at", ""),
        "last_seen_at": target.get("last_seen_at", ""),
        "is_admin": admin_flag,
        "plan": target.get("plan", settings.default_plan),
        "plan_overrides": target.get("plan_overrides", {}),
        "extra_usage_opt_in": bool(target.get("extra_usage_opt_in", False)),
        "usage": summary,
        "lifetime": lifetime_totals,
        "by_model": by_model,
        "daily_series": series,
        "recent_runs": recent,
        "invitees": invitees,
    }


@router.get("/usage/overview")
async def usage_overview(
    user: dict = Depends(get_admin_user),
):
    """Global usage / cost overview for the current calendar month."""
    since = usage_service.month_start()
    ov = await usage_service.overview(since)

    # Enrich top users with display names.
    top = ov.get("top_users", [])
    names = await names_for_ids([t["_id"] for t in top])
    ov["top_users"] = [{
        "user_id": t["_id"],
        "display_name": (names.get(t["_id"], {}).get("display_name")
                         or names.get(t["_id"], {}).get("github_login")
                         or names.get(t["_id"], {}).get("email")
                         or "—"),
        "cost_usd": round(t.get("cost_usd", 0.0), 6),
        "total_tokens": int(t.get("total_tokens", 0)),
        "run_count": int(t.get("run_count", 0)),
    } for t in top]

    return ov


@router.get("/plans")
async def list_plans(user: dict = Depends(get_admin_user)):
    """The available plan tiers (for the admin plan editor)."""
    return [{
        "key": p.key,
        "label": p.label,
        "monthly_budget_usd": p.monthly_budget_usd,
        "overage_allowed": p.overage_allowed,
    } for p in plans.PLANS.values()]


@router.put("/users/{user_id}/repos")
async def update_user_repos(
    user_id: str,
    body: UserReposUpdate,
    user: dict = Depends(get_admin_user),
):
    """Update the allowed repositories for a viewer user (admin only)."""
    updated = await update_allowed_repos(user_id, body.allowed_repo_ids)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Benutzer nicht gefunden oder kein Viewer-Konto.",
        )
    return {"status": "updated", "allowed_repo_ids": updated.get("allowed_repo_ids", [])}


@router.put("/users/{user_id}/plan")
async def update_user_plan(
    user_id: str,
    body: UserPlanUpdate,
    user: dict = Depends(get_admin_user),
):
    """Assign a plan tier, optional budget override, and overage opt-in (admin only)."""
    if body.plan not in plans.PLANS:
        raise HTTPException(status_code=400, detail="Unbekannter Tarif.")
    updated = await set_user_plan(
        user_id,
        plan=body.plan,
        monthly_budget_usd=body.monthly_budget_usd,
        extra_usage_opt_in=body.extra_usage_opt_in,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    return {
        "status": "updated",
        "plan": updated.get("plan"),
        "plan_overrides": updated.get("plan_overrides", {}),
        "extra_usage_opt_in": updated.get("extra_usage_opt_in", False),
    }
