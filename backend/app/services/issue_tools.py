# app/services/issue_tools.py
"""
Chat-only agent tools that draft issue changes for the user to confirm.

Each tool validates against GitHub (labels exist, issue isn't a PR, …) and
stores a draft via issue_actions. Nothing is written to GitHub here — the UI
renders the draft as a confirmation card keyed by the returned action_id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional

import anyio
from fastapi import HTTPException
from github import GithubException
from pydantic_ai import Tool

from app.services import issue_actions
from app.services.github_service import GitHubService
from app.services.issue_writes import (
    IssueWriteError,
    build_comment,
    build_create,
    build_update,
    describe_github_error,
)

# How often the model may resend a call with schema-invalid arguments.
_MAX_RETRIES = 3


class _DraftRejected(Exception):
    """Validation or GitHub failure, reported back to the model as the tool result."""

WRITE_INSTRUCTIONS = """
## Issues anlegen und bearbeiten
- Du kannst Issues anlegen, bearbeiten (Titel, Beschreibung, Labels, Zuweisungen, schließen/wiedereröffnen) \
und kommentieren – aber nur als **Entwurf**: Die Tools `propose_create_issue`, `propose_update_issue` und \
`propose_issue_comment` erstellen einen Entwurf, den der Nutzer im Chat prüfen, anpassen und bestätigen muss.
- Behaupte nie, dass etwas auf GitHub angelegt oder geändert wurde. Sage stattdessen in einem Satz, dass der \
Entwurf zur Bestätigung bereitsteht. Der Nutzer sieht den Entwurf als Karte im Chat – fasse seinen Inhalt \
nicht zusammen und wiederhole ihn nicht.
- Ein Entwurf existiert nur, wenn das Tool eine `action_id` zurückgegeben hat. Antwortet es mit \
„Kein Entwurf erstellt“ (z.B. unbekanntes Label), rufe es mit korrigierten Angaben erneut auf – oder erkläre \
dem Nutzer das Problem bzw. frage nach, wenn die Korrektur seinem Wunsch widerspräche. Gib Entwürfe nie als Text oder JSON in deiner Antwort aus.
- Erstelle Entwürfe nur, wenn der Nutzer das möchte. Pro Anliegen ein Entwurf.
- Lies vor dem Bearbeiten das Issue mit `get_issue_detail`. Wenn du die Beschreibung ersetzt, übergib die \
vollständige neue Beschreibung und erhalte bestehende Inhalte, sofern der Nutzer nichts anderes will. \
Für Ergänzungen (z.B. Status-Updates) nutze `append_to_body`. Ist `body_truncated` wahr, ersetze die \
Beschreibung nie – nutze nur `append_to_body`.
- Schreibe Titel und Texte in der Sprache der bestehenden Issues des Repositories. Strukturiere Beschreibungen \
mit Markdown (z.B. Kontext, Ziel, Akzeptanzkriterien als Checkliste), wenn es dem Issue hilft.
- Verwende nur existierende Labels; bei Unklarheit frage nach.
- Entwürfe gelten immer für das Repository dieses Chats. Meint der Nutzer ein anderes Repository, erstelle \
keinen Entwurf, sondern weise darauf hin, dass er dafür einen Chat in jenem Repository öffnen muss.
"""


@dataclass
class IssueWriteContext:
    """Who the drafts belong to. Only set for users who may write."""
    user_id: str
    chat_id: Optional[str]


def build_issue_tools(github_service: GitHubService, ctx: IssueWriteContext) -> list[Tool]:
    repo = github_service.repo_full_name

    async def _validate(fn, **kwargs):
        # Business outcomes (unknown label, no change, GitHub down…) go back to
        # the model as text — not ModelRetry, which would burn the retry budget
        # and crash the run on the 4th rejection.
        try:
            return await anyio.to_thread.run_sync(lambda: fn(github_service, **kwargs))
        except IssueWriteError as e:
            raise _DraftRejected(str(e)) from e
        except GithubException as e:
            raise _DraftRejected(describe_github_error(e)) from e
        except HTTPException as e:
            raise _DraftRejected(str(e.detail)) from e

    def _rejected(e: _DraftRejected) -> str:
        return f"Kein Entwurf erstellt: {e}"

    async def _store(**draft) -> str:
        action_id = await issue_actions.create_draft(
            user_id=ctx.user_id, chat_id=ctx.chat_id, repo=repo, **draft,
        )
        return json.dumps({
            "action_id": action_id,
            "message": "Entwurf erstellt. Er wird erst nach Bestätigung durch den Nutzer auf GitHub übernommen.",
        }, ensure_ascii=False)

    async def propose_create_issue(
        title: str,
        body: str = "",
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None,
    ) -> str:
        """Erstellt einen Entwurf für ein neues Issue, den der Nutzer bestätigen muss.

        Args:
            title: Kurzer, aussagekräftiger Titel.
            body: Beschreibung in Markdown.
            labels: Namen existierender Labels.
            assignees: GitHub-Benutzernamen, denen das Issue zugewiesen wird.
        """
        try:
            proposed = await _validate(
                build_create, title=title, body=body, labels=labels, assignees=assignees,
            )
        except _DraftRejected as e:
            return _rejected(e)
        return await _store(kind="create_issue", proposed=proposed)

    async def propose_update_issue(
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        append_to_body: Optional[str] = None,
        add_labels: Optional[list[str]] = None,
        remove_labels: Optional[list[str]] = None,
        add_assignees: Optional[list[str]] = None,
        remove_assignees: Optional[list[str]] = None,
        state: Optional[Literal["open", "closed"]] = None,
        state_reason: Optional[Literal["completed", "not_planned"]] = None,
    ) -> str:
        """Erstellt einen Entwurf für Änderungen an einem bestehenden Issue, den der Nutzer bestätigen muss.

        Nur angegebene Felder werden geändert.

        Args:
            issue_number: Nummer des Issues.
            title: Neuer Titel.
            body: Vollständige neue Beschreibung (ersetzt die bisherige).
            append_to_body: Text, der unten an die bisherige Beschreibung angehängt wird.
            add_labels: Labels, die hinzugefügt werden.
            remove_labels: Labels, die entfernt werden.
            add_assignees: Benutzer, die zugewiesen werden.
            remove_assignees: Benutzer, deren Zuweisung entfernt wird.
            state: 'closed' zum Schließen, 'open' zum Wiedereröffnen.
            state_reason: Grund beim Schließen: 'completed' (erledigt) oder 'not_planned' (nicht geplant).
        """
        try:
            proposed, current = await _validate(
                build_update,
                issue_number=issue_number, title=title, body=body, append_to_body=append_to_body,
                add_labels=add_labels, remove_labels=remove_labels,
                add_assignees=add_assignees, remove_assignees=remove_assignees,
                state=state, state_reason=state_reason,
            )
        except _DraftRejected as e:
            return _rejected(e)
        return await _store(
            kind="update_issue", issue_number=issue_number, proposed=proposed, current=current,
        )

    async def propose_issue_comment(issue_number: int, body: str) -> str:
        """Erstellt einen Entwurf für einen Kommentar zu einem Issue, den der Nutzer bestätigen muss.

        Args:
            issue_number: Nummer des Issues.
            body: Kommentartext in Markdown.
        """
        try:
            proposed, current = await _validate(build_comment, issue_number=issue_number, body=body)
        except _DraftRejected as e:
            return _rejected(e)
        return await _store(
            kind="comment", issue_number=issue_number, proposed=proposed, current=current,
        )

    return [
        Tool(fn, max_retries=_MAX_RETRIES, sequential=True)
        for fn in (propose_create_issue, propose_update_issue, propose_issue_comment)
    ]
