# app/services/agent_runner.py
"""
Single-agent runner with SSE streaming.
Matches chatforen's _stream_chat / _stream_agent_events / _process_stream_event pattern.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import AsyncGenerator

from llama_index.core.agent.workflow import (
    FunctionAgent,
    AgentStream,
    AgentOutput,
    ToolCall,
    ToolCallResult,
)
from llama_index.core.llms import ChatMessage
from llama_index.core.memory import Memory

from app.services.llm_factory import LLMConfig, build_llm
from app.services.github_service import GitHubService
from app.tools.registry import build_all_tools
from app.utils import trunc, sse_event, safe_serialize_kwargs

logger = logging.getLogger(__name__)

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

        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            today=date.today().isoformat(),
            repo=github_service.repo_full_name,
        )
        llm_config.system_prompt = self.system_prompt
        self.llm = build_llm(llm_config)

        self.agent = FunctionAgent(
            llm=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            allow_parallel_tool_calls=False,
        )

    async def run_streaming(
        self,
        query: str,
        chat_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run the agent and yield SSE-formatted events."""
        logger.info("Agent run: query=%r", query)

        yield sse_event({"type": "status", "status": "started"})

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

        final_response = ""

        try:
            handler = self.agent.run(user_msg=query, memory=memory)

            async for event in handler.stream_events():
                if isinstance(event, AgentStream):
                    delta = event.delta or ""
                    if delta:
                        final_response += delta
                        yield sse_event({"type": "token", "content": delta})

                elif isinstance(event, AgentOutput):
                    if event.tool_calls:
                        logger.info("Tool calls pending: %d", len(event.tool_calls))

                elif isinstance(event, ToolCall):
                    logger.info("ToolCall: %s", event.tool_name)
                    yield sse_event({
                        "type": "tool_call",
                        "name": event.tool_name,
                        "id": event.tool_id,
                        "input": safe_serialize_kwargs(event.tool_kwargs),
                    })

                elif isinstance(event, ToolCallResult):
                    output_str = str(event.tool_output.content) if event.tool_output else ""
                    logger.info("ToolCallResult: %s -> %d chars", event.tool_name, len(output_str))
                    yield sse_event({
                        "type": "tool_result",
                        "name": event.tool_name,
                        "id": event.tool_id,
                        "output": trunc(output_str, 2000),
                    })

            yield sse_event({
                "type": "status",
                "status": "completed",
                "response": final_response,
            })

        except Exception as e:
            logger.exception("Agent execution failed")
            yield sse_event({
                "type": "status",
                "status": "error",
                "error": str(e),
            })
