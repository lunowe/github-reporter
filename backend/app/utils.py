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


def sse_event(
    data: dict,
    *,
    event_id: str | None = None,
    event_type: str | None = None,
) -> str:
    """
    Format a dict as a full SSE frame.

    `id:` enables client-side resume (Last-Event-ID on reconnect).
    `event:` is the SSE event type — when set, clients can branch via
    EventSource.addEventListener('<type>', …) or our manual parser.
    """
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def sse_comment(text: str) -> str:
    """SSE comment frame — used as a keepalive. Ignored by clients."""
    return f": {text}\n\n"


def safe_serialize_kwargs(obj) -> dict:
    """Serialize tool kwargs to a JSON-safe dict."""
    try:
        if isinstance(obj, dict):
            return {k: str(v) for k, v in obj.items()}
        return {"raw": str(obj)}
    except Exception:
        return {"raw": "..."}
