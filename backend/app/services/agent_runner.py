# app/services/agent_runner.py
"""
Single-agent runner that yields typed (event_type, data) tuples.

Formatting for the wire (SSE) happens at the HTTP boundary; the runner itself
stays transport-agnostic so stream_manager can shove these events through Redis
without re-parsing.

Provider/tool errors propagate out of `run_streaming` / `run_once` — the caller
decides how to surface them (stream_manager marks the run as `error`).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import AsyncGenerator, Optional

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    UserPromptPart,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from app.services.llm_factory import LLMConfig, build_llm
from app.services.github_service import GitHubService
from app.services.issue_tools import WRITE_INSTRUCTIONS, IssueWriteContext, build_issue_tools
from app.tools.registry import GitHubTool, build_all_tools
from app.utils import trunc, safe_serialize_kwargs

logger = logging.getLogger(__name__)

# Anthropic requires an explicit output cap; the SDK default is too low for
# multi-section status reports.
_ANTHROPIC_MAX_TOKENS = 16_000

# How often the model may resend a tool call with invalid arguments.
_TOOL_MAX_RETRIES = 3


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


def _to_agent_tool(tool: GitHubTool) -> Tool:
    """
    Adapt a GitHubTool to Pydantic AI. The single parameter is annotated with
    the tool's schema, so Pydantic AI exposes the schema's fields directly and
    validates arguments itself (invalid args → the model is asked to retry).
    GitHub/API failures are returned to the model as text so it can adapt
    instead of aborting the whole run. Sync PyGithub calls run in a worker thread.
    """
    def call(args) -> str:
        try:
            return tool.fn(**args.model_dump())
        except Exception as e:  # noqa: BLE001 — surface to the model, not the user
            logger.warning("Tool %s failed: %s", tool.name, e)
            return f"Fehler beim Abrufen der GitHub-Daten: {e}"

    # Set at runtime: the schema class is only known per tool.
    call.__annotations__ = {"args": tool.schema, "return": str}

    return Tool(
        call,
        name=tool.name,
        description=tool.description,
        max_retries=_TOOL_MAX_RETRIES,
        # PyGithub isn't built for concurrent use; keep calls one at a time.
        sequential=True,
    )


def _to_message_history(chat_history: list[dict] | None) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for msg in chat_history or []:
        content = msg.get("content") or ""
        if not content:
            continue
        role = msg.get("role", "user")
        if role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=content)]))
    return messages


class AgentRunner:
    """Builds and runs a single Pydantic AI agent with GitHub tools."""

    def __init__(
        self,
        llm_config: LLMConfig,
        github_service: GitHubService,
        write_context: Optional[IssueWriteContext] = None,
    ):
        """`write_context` enables the issue-draft tools; omit it for read-only
        callers (viewers, automations)."""
        self.github_service = github_service
        self.provider = llm_config.provider
        self.model = llm_config.model

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            repo=github_service.repo_full_name,
        )
        tools = [_to_agent_tool(t) for t in build_all_tools(github_service)]
        if write_context is not None:
            system_prompt += WRITE_INSTRUCTIONS
            tools += build_issue_tools(github_service, write_context)

        # Accumulates real provider token counts across every tool-calling turn
        # of a run — including runs that end in an error or a cancel.
        self._usage = RunUsage()

        self.agent = Agent(
            build_llm(llm_config),
            instructions=system_prompt,
            tools=tools,
            model_settings=(
                ModelSettings(max_tokens=_ANTHROPIC_MAX_TOKENS)
                if self.provider == "anthropic" else None
            ),
        )

    def usage(self) -> dict:
        """Token usage for the most recent run."""
        prompt = self._usage.input_tokens or 0
        completion = self._usage.output_tokens or 0
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cached_tokens": self._usage.cache_read_tokens or 0,
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

        If `cancel_event` is set mid-stream we break out of the loop; leaving
        the `run_stream_events` context cancels the run so no more tool calls fire.
        """
        logger.info("Agent run: query=%r", query)
        self._usage = RunUsage()

        yield "status", {"status": "started"}

        async with self.agent.run_stream_events(
            query,
            message_history=_to_message_history(chat_history),
            usage=self._usage,
        ) as events:
            async for event in events:
                if cancel_event is not None and cancel_event.is_set():
                    break

                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    if event.part.content:
                        yield "token", {"content": event.part.content}

                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    if event.delta.content_delta:
                        yield "token", {"content": event.delta.content_delta}

                elif isinstance(event, FunctionToolCallEvent):
                    logger.info("ToolCall: %s", event.part.tool_name)
                    yield "tool_call", {
                        "name": event.part.tool_name,
                        "id": event.tool_call_id,
                        "input": safe_serialize_kwargs(event.part.args_as_dict()),
                    }

                elif isinstance(event, FunctionToolResultEvent):
                    content = event.part.content
                    output_str = content if isinstance(content, str) else str(content)
                    logger.info("ToolCallResult: %s -> %d chars", event.part.tool_name, len(output_str))
                    yield "tool_result", {
                        "name": event.part.tool_name,
                        "id": event.tool_call_id,
                        "output": trunc(output_str, 2000),
                    }

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
        self._usage = RunUsage()

        result = await self.agent.run(
            query,
            message_history=_to_message_history(chat_history),
            usage=self._usage,
        )
        return result.output
