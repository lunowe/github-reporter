/**
 * Admin usage / cost insights — overview dashboard, per-user detail, and
 * plan/limit management. Admin-only endpoints under /api/admin.
 */

export interface UsageSummary {
  plan: string;
  plan_label: string;
  budget_usd: number | null; // null = unlimited
  extra_usage_opt_in: boolean;
  overage_allowed: boolean;
  period_cost_usd: number;
  period_tokens: number;
  run_count: number;
  pct_used: number | null;
  overage_usd: number;
  last_activity: string | null;
}

export interface Totals {
  cost_usd: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  run_count: number;
}

export interface ByModel {
  provider: string;
  model: string;
  cost_usd: number;
  total_tokens: number;
  run_count: number;
}

export interface DailyPoint {
  date: string;
  cost_usd: number;
  total_tokens: number;
  run_count: number;
}

export interface TopUser {
  user_id: string;
  display_name: string;
  cost_usd: number;
  total_tokens: number;
  run_count: number;
}

export interface UsageOverview {
  period_start: string;
  period: Totals;
  lifetime: Totals;
  by_model: ByModel[];
  by_kind: Record<string, { cost_usd: number; run_count: number }>;
  daily_series: DailyPoint[];
  top_users: TopUser[];
}

export interface RecentRun {
  kind: string;
  repo: string;
  model: string;
  provider: string;
  total_tokens: number;
  cost_usd: number;
  status: string;
  created_at: string;
}

export interface Invitee {
  id: string;
  display_name: string;
  email: string;
  role: string;
  created_at: string;
  last_seen_at: string;
  period_cost_usd?: number;
  period_tokens?: number;
}

export interface UserDetail {
  id: string;
  display_name: string;
  github_login: string | null;
  email: string;
  role: string;
  auth_method: string;
  activated: boolean;
  created_at: string;
  last_seen_at: string;
  is_admin: boolean;
  plan: string;
  plan_overrides: { monthly_budget_usd?: number };
  extra_usage_opt_in: boolean;
  suspended: boolean;
  allowed_models: string[];
  usage: UsageSummary;
  lifetime: Totals;
  by_model: ByModel[];
  daily_series: DailyPoint[];
  recent_runs: RecentRun[];
  invitees: Invitee[];
}

export interface PlanTier {
  key: string;
  label: string;
  monthly_budget_usd: number | null;
  overage_allowed: boolean;
}

export interface LimitsUpdateBody {
  plan: string;
  monthly_budget_usd: number | null;
  extra_usage_opt_in: boolean;
  suspended: boolean;
  allowed_models: string[];
}

export interface UsageAdjustBody {
  reset?: boolean;
  credit_usd?: number | null;
  note?: string;
}

export function useAdminStats() {
  const { apiFetch } = useApi();

  function fetchOverview() {
    return apiFetch<UsageOverview>("/api/admin/usage/overview");
  }

  function fetchUserDetail(userId: string) {
    return apiFetch<UserDetail>(`/api/admin/users/${userId}`);
  }

  function fetchPlans() {
    return apiFetch<PlanTier[]>("/api/admin/plans");
  }

  function updateUserLimits(userId: string, body: LimitsUpdateBody) {
    return apiFetch(`/api/admin/users/${userId}/limits`, {
      method: "PUT",
      body,
    });
  }

  function adjustUsage(userId: string, body: UsageAdjustBody) {
    return apiFetch(`/api/admin/users/${userId}/usage/adjust`, {
      method: "POST",
      body,
    });
  }

  return { fetchOverview, fetchUserDetail, fetchPlans, updateUserLimits, adjustUsage };
}

// ── Shared formatting helpers (auto-imported by Nuxt) ──

export function formatUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (!n) return "$0.00";
  if (Math.abs(n) < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(n);
}
