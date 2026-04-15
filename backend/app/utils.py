# app/utils.py
"""Shared utilities used across backend modules."""

import json


def trunc(text: str | None, limit: int = 200) -> str:
    """Truncate text with ellipsis. Handles None."""
    if not text:
        return ""
    return text[:limit] + ("..." if len(text) > limit else "")


def to_tool_output(data) -> str:
    """Serialize tool output for LLM consumption."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def sse_event(data: dict) -> str:
    """Format dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def safe_serialize_kwargs(obj) -> dict:
    """Serialize tool kwargs to a JSON-safe dict."""
    try:
        if isinstance(obj, dict):
            return {k: str(v) for k, v in obj.items()}
        return {"raw": str(obj)}
    except Exception:
        return {"raw": "..."}
