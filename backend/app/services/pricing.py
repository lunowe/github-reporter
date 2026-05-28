# app/services/pricing.py
"""
LLM pricing table and cost computation.

Prices are USD per 1,000,000 tokens, split into input (prompt) and output
(completion). A separate, optional cached-input rate covers prompt-cache reads
where a provider reports them.

The computed cost is **snapshotted** onto each usage event at write time (see
``usage_service.record_usage``) together with ``PRICING_VERSION`` so historical
cost stays stable even when this table is later edited.

To update prices: edit ``MODEL_PRICING`` and bump ``PRICING_VERSION``. Keys are
matched case-insensitively, longest-prefix-first, so a generic ``"claude"`` entry
acts as a fallback for any unlisted Claude model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Bump whenever MODEL_PRICING changes so stored events remain explainable.
PRICING_VERSION = "2026-05"


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens."""
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None  # prompt-cache read rate, if known


# Keyed by a normalized (lowercase) model id or prefix. Lookup tries the exact
# id first, then the longest matching prefix. Keep the most specific keys longer
# than their fallbacks so prefix matching resolves them first.
MODEL_PRICING: dict[str, ModelPrice] = {
    # ── Google Gemini ──
    "gemini-3-pro": ModelPrice(2.00, 12.00, cached_input_per_mtok=0.50),
    "gemini-3-flash": ModelPrice(0.30, 2.50, cached_input_per_mtok=0.075),
    "gemini-2.5-pro": ModelPrice(1.25, 10.00, cached_input_per_mtok=0.31),
    "gemini-2.5-flash": ModelPrice(0.30, 2.50, cached_input_per_mtok=0.075),
    "gemini-1.5-pro": ModelPrice(1.25, 5.00),
    "gemini-1.5-flash": ModelPrice(0.075, 0.30),
    "gemini": ModelPrice(0.30, 2.50),  # fallback for any other gemini model

    # ── OpenAI ──
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gpt-4.1-nano": ModelPrice(0.10, 0.40),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    "gpt-4.1": ModelPrice(2.00, 8.00),
    "o3-mini": ModelPrice(1.10, 4.40),
    "o3": ModelPrice(2.00, 8.00),
    "o1-mini": ModelPrice(1.10, 4.40),
    "o1": ModelPrice(15.00, 60.00),
    "gpt": ModelPrice(2.50, 10.00),  # fallback for any other gpt model

    # ── Anthropic Claude ──
    "claude-opus-4": ModelPrice(15.00, 75.00, cached_input_per_mtok=1.50),
    "claude-sonnet-4": ModelPrice(3.00, 15.00, cached_input_per_mtok=0.30),
    "claude-haiku-4": ModelPrice(0.80, 4.00, cached_input_per_mtok=0.08),
    "claude-3-5-sonnet": ModelPrice(3.00, 15.00, cached_input_per_mtok=0.30),
    "claude-3-5-haiku": ModelPrice(0.80, 4.00, cached_input_per_mtok=0.08),
    "claude-3-opus": ModelPrice(15.00, 75.00),
    "claude": ModelPrice(3.00, 15.00),  # fallback for any other claude model
}

# Prefix keys are tried longest-first so e.g. "gpt-4o-mini" wins over "gpt".
_SORTED_KEYS = sorted(MODEL_PRICING.keys(), key=len, reverse=True)


@dataclass(frozen=True)
class CostBreakdown:
    input_cost_usd: float
    output_cost_usd: float
    cost_usd: float
    pricing_version: str
    priced: bool  # False when the model wasn't found (cost is 0, treat as estimate gap)


def price_for_model(model: str) -> ModelPrice | None:
    """Resolve a model name to its price via exact then longest-prefix match."""
    if not model:
        return None
    key = model.strip().lower()
    if key in MODEL_PRICING:
        return MODEL_PRICING[key]
    for prefix in _SORTED_KEYS:
        if key.startswith(prefix):
            return MODEL_PRICING[prefix]
    return None


def compute_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> CostBreakdown:
    """
    Compute the USD cost of a single LLM call.

    Cached prompt tokens (if any) are billed at the model's cached rate and
    subtracted from the regular input tokens. Falls back to the model's input
    rate for cached tokens when no cached rate is configured.
    """
    price = price_for_model(model)
    if price is None:
        logger.warning("No pricing configured for model %r — recording cost 0", model)
        return CostBreakdown(0.0, 0.0, 0.0, PRICING_VERSION, priced=False)

    cached = max(0, min(cached_tokens, prompt_tokens))
    regular_input = prompt_tokens - cached

    cached_rate = (
        price.cached_input_per_mtok
        if price.cached_input_per_mtok is not None
        else price.input_per_mtok
    )

    input_cost = (
        regular_input * price.input_per_mtok + cached * cached_rate
    ) / 1_000_000
    output_cost = completion_tokens * price.output_per_mtok / 1_000_000

    return CostBreakdown(
        input_cost_usd=round(input_cost, 6),
        output_cost_usd=round(output_cost, 6),
        cost_usd=round(input_cost + output_cost, 6),
        pricing_version=PRICING_VERSION,
        priced=True,
    )
