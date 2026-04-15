# app/services/llm_factory.py
"""
Simplified LLM Factory – adapted from chatforen.
Supports Gemini, OpenAI, and Anthropic via LlamaIndex.
"""

from typing import Optional, Any
from dataclasses import dataclass

from llama_index.llms.google_genai import GoogleGenAI
from llama_index.llms.openai import OpenAI as OpenAILLM
from llama_index.llms.anthropic import Anthropic
import google.genai.types as types


@dataclass
class LLMConfig:
    """Configuration for building an LLM instance."""
    provider: str
    model: str
    system_prompt: str = ""
    temperature: float = 1.0
    max_tokens: Optional[int] = None


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


def build_llm(config: LLMConfig) -> Any:
    """Build an LLM instance from configuration."""
    provider = config.provider

    if provider == "gemini":
        return _build_gemini(config)
    if provider == "openai":
        return _build_openai(config)
    if provider == "anthropic":
        return _build_anthropic(config)

    raise ValueError(f"Unknown provider: {provider}")


def _build_gemini(config: LLMConfig) -> GoogleGenAI:
    return GoogleGenAI(
        model=config.model,
        max_tokens=config.max_tokens,
        generation_config=types.GenerateContentConfig(
            temperature=config.temperature,
            system_instruction=config.system_prompt or None,
        ),
    )


def _build_openai(config: LLMConfig) -> OpenAILLM:
    return OpenAILLM(
        model=config.model,
        system_prompt=config.system_prompt or None,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
    )


def _build_anthropic(config: LLMConfig) -> Anthropic:
    return Anthropic(
        model=config.model,
        system_prompt=config.system_prompt or None,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
    )
