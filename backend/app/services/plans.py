# app/services/plans.py
"""
Plan tiers — the productization foundation.

Each tier carries a monthly *included* USD budget (the cost allowance bundled
with the plan). A user may additionally opt into "extra usage": pay-per-token
overage beyond the included budget, billed to them.

Enforcement (hard 429 when a non-opted-in user exceeds budget) lives in
``usage_service.check_limit`` and is gated behind ``settings.usage_limit_enforced``
— it is wired but switched off this iteration. This module only *describes*
the tiers and resolves the effective budget for a user.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    # Monthly included USD budget. None == unlimited (no cap).
    monthly_budget_usd: float | None
    # Whether users on this tier may opt into pay-per-token overage.
    overage_allowed: bool


PLANS: dict[str, Plan] = {
    "free": Plan(key="free", label="Free", monthly_budget_usd=5.0, overage_allowed=False),
    "pro": Plan(key="pro", label="Pro", monthly_budget_usd=50.0, overage_allowed=True),
    "unlimited": Plan(key="unlimited", label="Unlimited", monthly_budget_usd=None, overage_allowed=True),
}

# Used when a user has no stored plan and settings don't override.
FALLBACK_PLAN_KEY = "free"
# Tier granted to the configured admin regardless of stored value.
ADMIN_PLAN_KEY = "unlimited"


def get_plan(key: str | None, default: str = FALLBACK_PLAN_KEY) -> Plan:
    """Resolve a plan key to a Plan, falling back to the default tier."""
    return PLANS.get(key or "", PLANS.get(default, PLANS[FALLBACK_PLAN_KEY]))


def resolve_plan(user: dict, *, is_admin: bool = False, default_plan: str = FALLBACK_PLAN_KEY) -> Plan:
    """The tier a user effectively belongs to (admin always unlimited)."""
    if is_admin:
        return PLANS[ADMIN_PLAN_KEY]
    return get_plan(user.get("plan"), default=default_plan)


def effective_budget_usd(user: dict, *, is_admin: bool = False, default_plan: str = FALLBACK_PLAN_KEY) -> float | None:
    """
    The user's effective monthly budget in USD.

    A per-user override (``plan_overrides.monthly_budget_usd``) takes precedence
    over the tier's included budget. None == unlimited.
    """
    if is_admin:
        return None
    override = (user.get("plan_overrides") or {}).get("monthly_budget_usd")
    if override is not None:
        return float(override)
    return resolve_plan(user, is_admin=is_admin, default_plan=default_plan).monthly_budget_usd
