# Plan: Powerful Admin Panel — Usage Insights, Token/Cost Tracking & Plan Foundation

## Context

The admin panel today (`backend/app/routes/admin.py` + `frontend/app/pages/admin.vue`) only lists users and lets the admin edit a viewer's allowed repos. It has **no visibility into LLM usage or cost**, and there is no token tracking anywhere in the stack — the agent runs (`agent_runner.py`) discard provider usage data entirely.

To productize the app (rate limits, paid plans) we need three things, built in this order:

1. **Clean token & cost tracking** — capture real provider token counts on every LLM run (chat + automation), price them, and persist as an append-only event log.
2. **A much richer admin panel** — per-user usage & cost, the invitee graph (who invited whom), and a global cost/usage overview.
3. **The plan & rate-limit foundation** — model dollar-budget tiers + a per-user "extra usage" (pay-per-token overage) opt-in, with a hard-block (429) enforcement path that is **wired but switched off this iteration** (per "foundation first"). We surface usage-vs-budget softly now; flipping one settings flag turns on enforcement later.

This iteration delivers (1) and (2) fully, and the data model + inert enforcement hook for (3).

### Decisions locked with the user
- **Scope:** foundation first — tracking + admin insights now; plans/limits modeled + soft display, not hard-enforced yet.
- **Limit behavior (when enabled):** hard block with HTTP 429 once a non-opted-in user exceeds their monthly $ budget.
- **Plan model:** named tiers each with an *included* monthly USD budget; users may opt into "extra usage" = pay-per-token overage beyond the included budget (billed to them). Admin can override a user's budget and toggle their opt-in.

### Key technical finding (verified against installed `llama-index-core==0.14.12`)
Cross-provider token capture is solved by LlamaIndex itself. `llama_index.core.utilities.token_counting.get_tokens_from_response` normalizes usage across all three providers — it reads `response.raw["usage"]` / `response.raw["usage_metadata"]` (Gemini) / `additional_kwargs`, matching input keys `prompt_tokens`/`input_tokens`/`prompt_token_count` and output keys `completion_tokens`/`output_tokens`/`candidates_token_count`. A per-run `TokenCountingHandler` on a per-instance `CallbackManager` accumulates these across all of the agent's tool-calling turns, in both streaming and non-streaming paths, with a tiktoken estimate fallback only when a provider omits usage.

---

## Data model

### New collection `usage_events` (append-only, source of truth)
One document per completed/cancelled/errored LLM run (one chat run; one automation step):
```
user_id        str          # run owner (automation: the automation's owner)
kind           "chat" | "automation"
chat_id        str | None
automation_id  str | None
run_id         str | None   # automation run id
step_order     int | None   # automation step index
repo           str
provider       str          # gemini | openai | anthropic
model          str
prompt_tokens  int
completion_tokens int
total_tokens   int
cached_tokens  int          # best-effort, 0 if provider doesn't report
input_cost_usd float
output_cost_usd float
cost_usd       float        # snapshotted at write time
pricing_version str         # e.g. "2026-05" — explains historical cost
status         "complete" | "cancelled" | "error" | "partial"
created_at     datetime (UTC)
```
Indexes: `(user_id, created_at desc)`, `(created_at desc)`, `(model)`.
Aggregations are computed on demand via Mongo aggregation pipelines (volume is small; a monthly rollup can be added later if needed).

### User document additions (defaulted at read, backfilled by migration)
```
plan                 str   = "free"     # tier key
plan_overrides       dict  = {}         # optional, e.g. {"monthly_budget_usd": 50}
extra_usage_opt_in   bool  = False      # pay-per-token overage allowed for this user
```
The admin (resolved at runtime via `is_admin`) always maps to the unlimited tier regardless of stored value.

### Period definition
Calendar month in UTC. Current-period usage = `sum(cost_usd)` for the user where `created_at >= start_of_current_month`.

---

## Backend changes

### New files
- **`app/services/pricing.py`** — `MODEL_PRICING` table (USD per 1M tokens, input/output, optional cached-input) covering the models actually used (Gemini 3 flash/pro, GPT-4o / 4.1 / o-series, Claude Opus/Sonnet/Haiku). `PRICING_VERSION = "2026-05"`. Functions: `price_for_model(model)` (normalize + prefix-match fallback), `compute_cost(model, prompt, completion, cached=0) -> {input_cost_usd, output_cost_usd, cost_usd, pricing_version}`. Unknown model → cost 0 + a `logger.warning` so gaps are visible.
- **`app/services/plans.py`** — `PLANS: dict[str, Plan]` (e.g. `free`, `pro`, `unlimited`). `Plan` = `{key, label, monthly_budget_usd (None = unlimited), overage_allowed: bool}`. Helpers: `resolve_plan(user, settings)` (admin → unlimited; else stored `plan` → tier, applying `plan_overrides.monthly_budget_usd`), `effective_budget_usd(user, settings)`. `DEFAULT_PLAN` from settings.
- **`app/services/usage_service.py`** — the heart:
  - `record_usage(**event)` — insert a `usage_events` doc; never raises into the caller (best-effort, logged).
  - `period_usage(user_id, since)` / `lifetime_usage(user_id)` — aggregate `{cost_usd, total_tokens, prompt_tokens, completion_tokens, run_count}`.
  - `usage_summary(user, settings)` — `{plan, budget_usd, period_cost_usd, period_tokens, pct_used, overage_usd, extra_usage_opt_in, run_count}` for one user.
  - `bulk_period_usage(user_ids, since)` — single aggregation grouped by `user_id` (avoids N+1 in the admin list).
  - `overview(since)` — global totals, daily cost series, by-model and by-provider breakdown, chat-vs-automation split, top users by cost.
  - `user_daily_series(user_id, days)` and `recent_runs(user_id, limit)` for the detail view.
  - `check_limit(user, settings) -> {allowed: bool, reason: str|None, ...}` — over-budget & not opted-in ⇒ `allowed=False`. **Pure decision function, no HTTP.**
  - `ensure_indexes()`.

### Modified files
- **`app/services/agent_runner.py`** — in `__init__`, build `self._token_counter = TokenCountingHandler()` and `self._cb = CallbackManager([self._token_counter])`, assign `self.llm.callback_manager = self._cb` (per-instance — **never** mutate global `Settings.callback_manager`; would corrupt concurrent runs). Pass `callback_manager=self._cb` to `FunctionAgent(...)` if the signature accepts it. Add `def usage(self) -> dict` returning `{prompt_tokens, completion_tokens, total_tokens, provider, model}` read from the handler after a run. Safety net: if the handler reports `total == 0`, fall back to summing usage off the `AgentOutput.raw` events already iterated in the stream loop, using the same key normalization as `get_tokens_from_response`.
- **`app/routes/chat.py`** — in the `producer` `finally` block (after the run, regardless of complete/cancel/error), call `usage_service.record_usage(kind="chat", user_id, chat_id, repo, provider, model, status=msg_status, **agent_runner.usage())`. Wrapped in try/except so usage logging can't break the stream. (Optional, low-cost: also stamp the assistant message dict with its `usage` so per-chat cost can surface later — README backlog item.)
- **`app/services/automation_runner.py`** — change `_run_single_step` to return `(output, usage)`; in `execute_automation`'s per-step loop, `record_usage(kind="automation", user_id, automation_id, run_id, step_order=order, repo, provider, model, status, **usage)`.
- **`app/routes/admin.py`** — enrich + add endpoints (all `Depends(get_admin_user)`):
  - `GET /api/admin/users` → add per user: `plan`, `extra_usage_opt_in`, `invited_count`, `invited_by` (`{id, display_name}`), and a `usage` summary (period cost, budget, pct, tokens, run_count, last_activity). Efficient: one `bulk_period_usage` aggregation + one `users` aggregation grouped by `invited_by` for counts; join in Python.
  - `GET /api/admin/users/{user_id}` (new) → profile + lifetime & period usage + per-model breakdown + `user_daily_series` (30d) + `recent_runs` + invitees list (each with their period usage).
  - `GET /api/admin/usage/overview` (new) → `usage_service.overview(start_of_month)` plus a lifetime total.
  - `PUT /api/admin/users/{user_id}/plan` (new) → set `plan`, `plan_overrides.monthly_budget_usd`, `extra_usage_opt_in`; validate plan key against `PLANS`.
- **`app/services/user_service.py`** — add `plan`/`extra_usage_opt_in` defaults to `list_all_users` output and `create_email_user`/`upsert_from_github` `$setOnInsert`; extend `migrate_existing_users` to `$set {plan: default, extra_usage_opt_in: false}` where missing; add `count_invited_by(user_ids)` and `set_user_plan(user_id, ...)` helpers.
- **`app/models/api.py`** — add `UserPlanUpdate {plan: str, monthly_budget_usd: float|None, extra_usage_opt_in: bool}`. Keep admin responses as plain dicts (existing style).
- **`app/routes/auth.py`** — extend `_user_profile()` with `plan` and a compact `usage` summary (period cost, budget, pct, opt-in) so the frontend (and a user-facing "your usage" line) can read it from `/api/auth/me`.
- **`app/config.py`** + **`backend/.env.example`** — add `usage_limit_enforced: bool = False`, `default_plan: str = "free"` (+ optional `plan_*_budget_usd` env overrides documented).
- **`app/main.py`** — call `usage_service.ensure_indexes()` in lifespan; the user migration already runs there.

### Enforcement hook (wired, inert this iteration)
In `app/routes/chat.py`'s `chat()` (before starting the run), call `usage_service.check_limit(user, settings)`; if `settings.usage_limit_enforced` **and** `not allowed` ⇒ `raise HTTPException(429, detail={...})`. With `usage_limit_enforced=False` (default) it is a no-op. This makes "hard block" a one-flag switch later without code changes.

---

## Frontend changes (`frontend/app/`)

- **`composables/useAdminStats.ts`** (new) — `fetchOverview()`, `fetchUserDetail(id)`, `updateUserPlan(id, body)` via `useApi`.
- **`pages/admin.vue`** (modify) — add an **"Übersicht" (Overview)** tab (KPI cards: cost this month, tokens, active users, runs; a cost-over-time bar series; by-model breakdown; top-users table) and enrich the **Benutzer** tab: each row shows a plan badge + a month-cost-vs-budget quota bar + tokens + invited count; clicking opens a detail dialog.
- **`components/admin/UsageBar.vue`** (new) — small dependency-free quota bar (div/SVG, styled like the existing `dashboard/RateLimitDisplay.vue`). **No new chart library** — all charts are CSS/SVG bars.
- **`components/admin/UserDetailDialog.vue`** (new) — reuses `ui/dialog` (or `ui/sheet`): full per-user breakdown (period + lifetime, per-model, daily series, recent runs, invitees) and a **"Plan & Limits"** editor (tier select, budget override input, extra-usage toggle) calling `updateUserPlan`.
- **`composables/useAuth.ts`** (modify) — extend `AuthUser` with optional `plan` + `usage`.
- **`pages/settings.vue`** (modify, light) — show the signed-in user their own "Nutzung diesen Monat" (cost vs budget) from `/me`.

All German UI strings, matching the existing tone. Reuse existing `ui/` primitives (Card, Table, Badge, Dialog/Sheet, Tabs, Button, Input, Select).

---

## Verification

1. **Pricing/aggregation unit smoke (no external APIs):** a throwaway script (or `python -c`) that inserts synthetic `usage_events` and asserts `compute_cost` and `usage_service.period_usage`/`overview` return correct sums and budget %s. Run against the docker Mongo.
2. **End-to-end token capture:** `docker-compose up --build`, sign in as admin, send a chat with each provider that has a key configured; confirm a `usage_events` doc is written with non-zero `prompt/completion/total_tokens` and a sane `cost_usd`. Confirm an automation run records one event per step. Verify (Anthropic at minimum, since it always reports streaming usage) that counts come from the provider, not the tiktoken fallback (log the source).
3. **Admin panel:** load `/admin` → Overview tab shows non-zero KPIs and the cost series; Benutzer rows show cost/budget bars + invited counts; open a user → detail dialog shows per-model breakdown, daily series, invitees; edit the user's plan/budget/opt-in and confirm it persists (re-open dialog, and `GET /api/admin/users/{id}`).
4. **Enforcement path (kept off):** unit-call `check_limit` with a synthetic over-budget non-opted-in user → `allowed=False`; opted-in → `allowed=True`. Temporarily set `usage_limit_enforced=true` and confirm `POST /api/chat` returns 429 for the over-budget user, then revert the flag to `false`.
5. Confirm no regression for users without a `plan` field (migration backfills; resolver defaults).

## Out of scope (this iteration)
- Actual billing/payment integration for overage (we track overage $; charging is a later step).
- Turning on hard enforcement in production (flag stays `false`).
- Per-message cost UI in the chat view (data is captured; UI is backlog).
- Request-rate (req/day) limits and per-tier model allowlists (model supports adding later).
