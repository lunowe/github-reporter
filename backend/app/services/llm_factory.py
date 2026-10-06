# app/services/llm_factory.py
"""
LLM factory – maps our (provider, model) pair onto a Pydantic AI model.
Supports Gemini, OpenAI, and Anthropic.
"""

import logging
from dataclasses import dataclass

from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model, infer_model

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """The requested model can't be used (unknown provider, missing API key…)."""


@dataclass
class LLMConfig:
    """Configuration for building an LLM instance."""
    provider: str
    model: str


# Our provider names → Pydantic AI model-string prefixes.
_PROVIDER_PREFIX = {
    "gemini": "google",
    "openai": "openai",
    "anthropic": "anthropic",
}


def infer_provider(model_name: str) -> str:
    """Infer provider from model name."""
    model_lower = model_name.lower()
    if "gemini" in model_lower:
        return "gemini"
    if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
        return "openai"
    if "claude" in model_lower:
        return "anthropic"
    return "gemini"


def normalize_model_name(provider: str, model: str) -> str:
    """
    Fix up legacy model ids stored on existing chats/automations.
    Anthropic ids use hyphens ("claude-sonnet-4-6"); the UI used to send
    dotted versions ("claude-sonnet-4.6"), which the API rejects.
    """
    if provider == "anthropic":
        return model.replace(".", "-")
    return model


def build_llm(config: LLMConfig) -> Model:
    """
    Build a Pydantic AI model. Resolves the provider eagerly so a missing API
    key fails here — before a run starts — instead of mid-stream.
    """
    prefix = _PROVIDER_PREFIX.get(config.provider)
    if prefix is None:
        raise LLMUnavailableError(f"Unbekannter LLM-Anbieter: {config.provider}")

    model = normalize_model_name(config.provider, config.model)
    try:
        return infer_model(f"{prefix}:{model}")
    except UserError as e:
        logger.error("Cannot build model %s:%s: %s", prefix, model, e)
        raise LLMUnavailableError(
            f"Modell '{model}' ist derzeit nicht verfügbar (Anbieter nicht konfiguriert)."
        ) from e
