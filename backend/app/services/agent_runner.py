# app/services/agent_runner.py
"""
Single-agent runner that yields typed (event_type, data) tuples.

Formatting for the wire (SSE) happens at the HTTP boundary; the runner itself
stays transport-agnostic so stream_manager can shove these events through Redis
without re-parsing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import AsyncGenerator, Optional

from llama_index.core.agent.workflow import (
    FunctionAgent,
    AgentStream,
    AgentOutput,
    ToolCall,
    ToolCallResult,
)
from llama_index.core.llms import ChatMessage
from llama_index.core.memory import Memory
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

from app.services.llm_factory import LLMConfig, build_llm
from app.services.github_service import GitHubService
from app.tools.registry import build_all_tools
from app.utils import trunc, safe_serialize_kwargs

logger = logging.getLogger(__name__)

# Provider usage payloads use different key names; normalize across all three.
_INPUT_TOKEN_KEYS = ("prompt_tokens", "input_tokens", "prompt_token_count")
_OUTPUT_TOKEN_KEYS = ("completion_tokens", "output_tokens", "candidates_token_count")
_CACHED_TOKEN_KEYS = ("cache_read_input_tokens", "cached_content_token_count", "cached_tokens")


def _coerce_usage_dict(raw, additional_kwargs) -> dict:
    """Pull the usage mapping out of a raw provider response (or kwargs)."""
    usage = None
    if isinstance(raw, dict):
        usage = raw.get("usage") or raw.get("usage_metadata")
    elif raw is not None:
        usage = getattr(raw, "usage", None) or getattr(raw, "usage_metadata", None)
    if usage is None:
        usage = additional_kwargs or {}
    if usage and not isinstance(usage, dict):
        try:
            usage = usage.model_dump()
        except Exception:
            try:
                usage = dict(usage)
            except Exception:
                usage = {}
    return usage or {}


def _pick(usage: dict, keys: tuple[str, ...]) -> int:
    for k in keys:
        if k in usage and usage[k] is not None:
            try:
                return int(usage[k])
            except (TypeError, ValueError):
                return 0
    return 0


SYSTEM_PROMPT_TEMPLATE = """\
Du bist der **GitHub Projekt-Reporter** – ein KI-Assistent, der Projektmanagern und Teamleads \
einen klaren Überblick über den aktuellen Stand eines GitHub-Repositories gibt.

## Heutiges Datum
{today}

## Deine Aufgabe
- Beantworte Fragen zum Projektstatus klar und kompakt.
- Nutze **immer** die passenden Tools, um aktuelle Daten abzurufen – erfinde keine Informationen.
- Bei allgemeinen Fragen wie "Was ist der aktuelle Status?" nutze mehrere Tools (z.B. get_repo_summary + list_pull_requests + get_commits).
- Bei zeitbezogenen Fragen ("letzte Woche", "gestern") berechne die Datumswerte relativ zum heutigen Datum.

## Code-Browsing
- Nutze `browse_directory` um die Projektstruktur zu erkunden. Beginne mit dem Wurzelverzeichnis (path="").
- Nutze `read_file` um den Inhalt einzelner Dateien zu lesen. Bei großen Dateien lies zuerst die ersten ~100 Zeilen, \
  dann bei Bedarf weitere Abschnitte mit start_line/end_line.
- Navigiere gezielt: zuerst die Struktur verstehen, dann relevante Dateien öffnen.

## Branch-Vergleich
- Nutze `compare_branches` um Unterschiede zwischen Branches zu sehen (z.B. "Was ist in develop neu gegenüber main?").

## Ausgabeformat
- Antworte auf **Deutsch**.
- Verwende **klare, verständliche Sprache** – vermeide Fachjargon, erkläre technische Begriffe kurz, es sind Projektmanager und Teamleads ohne tiefes Entwicklerwissen deine Hauptnutzer.
- Technische Begriffe (PR, Commit, Branch, CI, Merge, Issue) bleiben auf **Englisch**.
- Fasse zusammen – liste nicht einfach rohe Daten auf, sondern gib einen verständlichen Überblick.
- Wenn es viele Ergebnisse gibt, gruppiere sie sinnvoll (z.B. nach Autor, nach Bereich, nach Status).
- Bei Code-Fragen: zeige relevante Code-Ausschnitte und erkläre sie.

## Repository
Du arbeitest mit dem Repository **{repo}**.
"""


class AgentRunner:
    """Builds and runs a single FunctionAgent with GitHub tools."""

    def __init__(
        self,
        llm_config: LLMConfig,
        github_service: GitHubService,
    ):
        self.github_service = github_service
        self.tools = build_all_tools(github_service)
        self.provider = llm_config.provider
        self.model = llm_config.model

        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            repo=github_service.repo_full_name,
        )
        llm_config.system_prompt = self.system_prompt
        self.llm = build_llm(llm_config)

        # Per-instance token accounting. A fresh CallbackManager is attached to
        # *this* LLM only — never the global Settings — so concurrent runs can't
        # cross-contaminate. The handler accumulates real provider token counts
        # (tiktoken estimate fallback) across every tool-calling turn in a run.
        self._token_counter = TokenCountingHandler()
        self.llm.callback_manager = CallbackManager([self._token_counter])

        # Fallback accumulators, summed off AgentOutput.raw during the stream in
        # case the callback doesn't fire for a given provider/version.
        self._fallback_prompt = 0
        self._fallback_completion = 0
        self._cached_tokens = 0

        self.agent = FunctionAgent(
            llm=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            allow_parallel_tool_calls=False,
        )

    def _reset_usage(self) -> None:
        self._token_counter.reset_counts()
        self._fallback_prompt = 0
        self._fallback_completion = 0
        self._cached_tokens = 0

    def _accumulate_from_output(self, event: AgentOutput) -> None:
        """Best-effort: sum usage from one AgentOutput's raw provider response."""
        try:
            additional = {}
            if event.response is not None:
                additional = getattr(event.response, "additional_kwargs", {}) or {}
            usage = _coerce_usage_dict(event.raw, additional)
            if not usage:
                return
            self._fallback_prompt += _pick(usage, _INPUT_TOKEN_KEYS)
            self._fallback_completion += _pick(usage, _OUTPUT_TOKEN_KEYS)
            self._cached_tokens += _pick(usage, _CACHED_TOKEN_KEYS)
        except Exception:
            logger.debug("Usage extraction from AgentOutput failed", exc_info=True)

    def usage(self) -> dict:
        """
        Token usage for the most recent run. Prefers the callback handler's
        cumulative counts; falls back to the per-output sum if the handler saw
        nothing (e.g. provider didn't surface usage through the callback).
        """
        prompt = int(self._token_counter.prompt_llm_token_count or 0)
        completion = int(self._token_counter.completion_llm_token_count or 0)
        if prompt + completion == 0:
            prompt = self._fallback_prompt
            completion = self._fallback_completion
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cached_tokens": self._cached_tokens,
        }

    async def run_streaming(
        self,
        query: str,
        chat_history: list[dict] | None = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """
        Run the agent and yield (event_type, data) tuples.

        Event types: "status", "token", "tool_call", "tool_result".

        If `cancel_event` is set mid-stream we break out of the loop and ask the
        workflow handler to cancel so no more tool calls fire.
        """
        logger.info("Agent run: query=%r", query)
        self._reset_usage()

        yield "status", {"status": "started"}

        llama_messages: list[ChatMessage] = []
        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    llama_messages.append(ChatMessage(role="user", content=content))
                elif role == "assistant":
                    llama_messages.append(ChatMessage(role="assistant", content=content))

        memory = Memory.from_defaults(
            token_limit=200000,
            chat_history=llama_messages,
        )

        handler = self.agent.run(user_msg=query, memory=memory)

        try:
            async for event in handler.stream_events():
                if cancel_event is not None and cancel_event.is_set():
                    break

                if isinstance(event, AgentStream):
                    delta = event.delta or ""
                    if delta:
                        yield "token", {"content": delta}

                elif isinstance(event, AgentOutput):
                    self._accumulate_from_output(event)
                    if event.tool_calls:
                        logger.info("Tool calls pending: %d", len(event.tool_calls))

                elif isinstance(event, ToolCall):
                    logger.info("ToolCall: %s", event.tool_name)
                    yield "tool_call", {
                        "name": event.tool_name,
                        "id": event.tool_id,
                        "input": safe_serialize_kwargs(event.tool_kwargs),
                    }

                elif isinstance(event, ToolCallResult):
                    output_str = str(event.tool_output.content) if event.tool_output else ""
                    logger.info("ToolCallResult: %s -> %d chars", event.tool_name, len(output_str))
                    yield "tool_result", {
                        "name": event.tool_name,
                        "id": event.tool_id,
                        "output": trunc(output_str, 2000),
                    }
        finally:
            # If we're bailing early (cancel or exception), try to stop the handler
            # so no more tool calls fire. LlamaIndex's WorkflowHandler supports
            # cancellation; best-effort, since different versions expose different APIs.
            try:
                if hasattr(handler, "cancel_run"):
                    cancel_result = handler.cancel_run()
                    if asyncio.iscoroutine(cancel_result):
                        await cancel_result
                elif hasattr(handler, "cancel"):
                    handler.cancel()
            except Exception:
                logger.debug("Workflow handler cancel failed", exc_info=True)

    async def run_once(
        self,
        query: str,
        chat_history: list[dict] | None = None,
    ) -> str:
        """
        Run the agent non-streaming and return the final response text.
        Used by automations and other non-interactive callers.
        Raises on failure so the caller can log/store the error.
        """
        logger.info("Agent run_once: query=%r", query)
        self._reset_usage()

        llama_messages: list[ChatMessage] = []
        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    llama_messages.append(ChatMessage(role=role, content=content))

        memory = Memory.from_defaults(
            token_limit=200000,
            chat_history=llama_messages,
        )

        final_response = ""

        handler = self.agent.run(user_msg=query, memory=memory)
        async for event in handler.stream_events():
            if isinstance(event, AgentStream):
                delta = event.delta or ""
                if delta:
                    final_response += delta
            elif isinstance(event, AgentOutput):
                self._accumulate_from_output(event)
            elif isinstance(event, ToolCall):
                logger.info("ToolCall: %s", event.tool_name)
            elif isinstance(event, ToolCallResult):
                output_str = str(event.tool_output.content) if event.tool_output else ""
                logger.info(
                    "ToolCallResult: %s -> %d chars",
                    event.tool_name,
                    len(output_str),
                )

        return final_response
