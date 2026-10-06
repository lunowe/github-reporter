# app/services/issue_writes.py
"""
Issue write logic shared by chat drafts (issue_actions), and the MCP server.

Everything here is synchronous (PyGithub) — callers run it in a worker thread.
Validation problems raise IssueWriteError with a German message that can be
shown to the model (so it can correct itself) or to the user.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, Optional

from github import GithubException

from app.services.github_service import ISSUE_BODY_LIMIT, GitHubService

Kind = Literal["create_issue", "update_issue", "comment"]

MAX_TITLE_LEN = 256
MAX_BODY_LEN = 65_000  # GitHub's limit is 65,536 characters


class IssueWriteError(Exception):
    """A write can't be performed as requested (message is user/model-facing)."""


# ── Validation ─────────────────────────────────────────────────────────────

# Zero-width characters would let an "empty-looking" title through.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
# Characters that render as blank but aren't whitespace or format characters.
_BLANK_LOOKING = {"\u115f", "\u1160", "\u3164", "\uffa0", "\u2800", "\u180e"}


def _is_visible(ch: str) -> bool:
    return (
        not ch.isspace()
        and ch not in _BLANK_LOOKING
        and unicodedata.category(ch) not in ("Cf", "Cc", "Mn", "Me", "Zs")
    )


def check_title(title: str) -> str:
    title = _INVISIBLE.sub("", title or "").strip()
    if not any(_is_visible(ch) for ch in title):
        raise IssueWriteError("Der Titel darf nicht leer sein.")
    if len(title) > MAX_TITLE_LEN:
        raise IssueWriteError(f"Der Titel ist zu lang (max. {MAX_TITLE_LEN} Zeichen).")
    return title


def check_body(body: str) -> str:
    body = body or ""
    if len(body) > MAX_BODY_LEN:
        raise IssueWriteError(f"Der Text ist zu lang (max. {MAX_BODY_LEN} Zeichen).")
    return body


def body_is_replaceable(current: dict) -> bool:
    """
    The agent only ever sees the first ISSUE_BODY_LIMIT characters of a body.
    A full replacement of a longer body would silently delete the rest.
    """
    return len(current.get("body") or "") <= ISSUE_BODY_LIMIT


def check_body_replaceable(current: dict) -> None:
    """Model-facing guard: refuse full replacement, point to appending."""
    if not body_is_replaceable(current):
        raise IssueWriteError(
            f"Die Beschreibung ist länger als {ISSUE_BODY_LIMIT} Zeichen und kann nicht vollständig "
            "ersetzt werden, ohne Inhalte zu verlieren. Nutze stattdessen append_to_body oder "
            "bearbeite das Issue direkt auf GitHub."
        )


def _resolve_labels(svc: GitHubService, names: list[str]) -> list[str]:
    """Map label names case-insensitively onto the repo's existing labels."""
    if not names:
        return []
    existing = svc.get_label_names()
    by_lower = {n.lower(): n for n in existing}
    resolved, unknown = [], []
    for name in names:
        match = by_lower.get(name.strip().lower())
        if match:
            if match not in resolved:
                resolved.append(match)
        else:
            unknown.append(name)
    if unknown:
        available = ", ".join(existing[:50]) or "keine"
        raise IssueWriteError(
            f"Unbekannte Labels: {', '.join(unknown)}. Verfügbare Labels: {available}."
        )
    return resolved


def _check_assignees(svc: GitHubService, logins: list[str]) -> list[str]:
    checked: list[str] = []
    for login in logins:
        login = login.strip().lstrip("@")
        if not login or login in checked:
            continue
        if not svc.is_assignable(login):
            raise IssueWriteError(
                f"'{login}' kann in diesem Repository keine Issues zugewiesen bekommen."
            )
        checked.append(login)
    return checked


def _load_issue(svc: GitHubService, issue_number: int) -> dict:
    try:
        snapshot = svc.get_issue_snapshot(issue_number)
    except GithubException as e:
        if e.status in (404, 410):
            raise IssueWriteError(f"Issue #{issue_number} wurde nicht gefunden.") from e
        raise
    if snapshot["is_pull_request"]:
        raise IssueWriteError(
            f"#{issue_number} ist ein Pull Request, kein Issue – das wird nicht unterstützt."
        )
    return snapshot


# ── Building drafts ────────────────────────────────────────────────────────

def build_create(
    svc: GitHubService,
    *,
    title: str,
    body: str = "",
    labels: Optional[list[str]] = None,
    assignees: Optional[list[str]] = None,
) -> dict:
    """Validate a new issue. Returns the `proposed` field set."""
    proposed: dict = {"title": check_title(title), "body": check_body(body)}
    if labels:
        proposed["labels"] = _resolve_labels(svc, labels)
    if assignees:
        proposed["assignees"] = _check_assignees(svc, assignees)
    return proposed


def build_update(
    svc: GitHubService,
    *,
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
) -> tuple[dict, dict]:
    """
    Validate an edit against the issue's current state. Returns
    (proposed, current): `proposed` holds only fields that actually change,
    with labels/assignees as the complete resulting sets.
    """
    if body is not None and append_to_body is not None:
        raise IssueWriteError("Entweder 'body' oder 'append_to_body' angeben, nicht beides.")

    current = _load_issue(svc, issue_number)
    proposed: dict = {}

    if title is not None and check_title(title) != current["title"]:
        proposed["title"] = check_title(title)

    if body is not None and body != current["body"]:
        check_body_replaceable(current)  # only full replacements; appends keep everything
    if append_to_body is not None and not append_to_body.strip():
        append_to_body = None
    if append_to_body:
        base = current["body"].rstrip()
        body = f"{base}\n\n{append_to_body.strip()}" if base else append_to_body.strip()
    if body is not None and check_body(body) != current["body"]:
        proposed["body"] = body

    if add_labels or remove_labels:
        # Removing a label the repo doesn't define is already satisfied — no error.
        removing = {n.strip().lower() for n in remove_labels or []}
        labels = [l for l in current["labels"] if l.lower() not in removing]
        for name in _resolve_labels(svc, add_labels or []):
            if name not in labels:
                labels.append(name)
        if sorted(labels) != sorted(current["labels"]):
            proposed["labels"] = labels

    if add_assignees or remove_assignees:
        removing = {a.strip().lstrip("@").lower() for a in remove_assignees or []}
        assignees = [a for a in current["assignees"] if a.lower() not in removing]
        for login in _check_assignees(svc, add_assignees or []):
            if login not in assignees:
                assignees.append(login)
        if sorted(assignees) != sorted(current["assignees"]):
            proposed["assignees"] = assignees

    if state is not None and state != current["state"]:
        proposed["state"] = state
        if state == "closed":
            proposed["state_reason"] = state_reason or "completed"
        else:
            proposed["state_reason"] = "reopened"

    if not proposed:
        raise IssueWriteError(
            f"Keine Änderung: Issue #{issue_number} hat diese Werte bereits."
        )
    return proposed, current


def build_comment(svc: GitHubService, *, issue_number: int, body: str) -> tuple[dict, dict]:
    """Validate a comment. Returns (proposed, current issue snapshot)."""
    body = check_body(body).strip()
    if not body:
        raise IssueWriteError("Der Kommentar darf nicht leer sein.")
    return {"body": body}, _load_issue(svc, issue_number)


# ── Executing ──────────────────────────────────────────────────────────────

# Fields whose value at apply time must still match the draft's snapshot.
_CONFLICT_FIELDS = ("title", "body", "labels", "assignees", "state")


def execute(
    svc: GitHubService,
    *,
    kind: Kind,
    proposed: dict,
    issue_number: Optional[int] = None,
    current: Optional[dict] = None,
) -> dict:
    """
    Perform the write on GitHub. For updates with a `current` snapshot, refuse
    when any field being changed was modified on GitHub since the snapshot —
    otherwise we'd silently overwrite someone else's edit.
    """
    if kind == "create_issue":
        created = svc.create_issue(
            title=check_title(proposed["title"]),
            body=check_body(proposed.get("body", "")),
            labels=proposed.get("labels"),
            assignees=proposed.get("assignees"),
        )
        # Without triage rights GitHub ignores labels/assignees instead of failing.
        set_labels, set_assignees = created.pop("labels"), created.pop("assignees")
        dropped = [
            *(l for l in proposed.get("labels") or [] if l not in set_labels),
            *(a for a in proposed.get("assignees") or [] if a not in set_assignees),
        ]
        if dropped:
            created["warning"] = (
                f"GitHub hat nicht alles übernommen ({', '.join(dropped)}) – vermutlich fehlen "
                "deinem Konto die Rechte, Labels oder Zuweisungen zu setzen."
            )
        return created

    if issue_number is None:
        raise IssueWriteError("Keine Issue-Nummer angegeben.")

    if kind == "comment":
        return svc.add_issue_comment(issue_number, check_body(proposed["body"]))

    if current is not None:
        latest = _load_issue(svc, issue_number)
        changed = [
            f for f in _CONFLICT_FIELDS
            if f in proposed and _normalized(latest[f]) != _normalized(current[f])
        ]
        if changed:
            raise IssueWriteError(
                f"Issue #{issue_number} wurde inzwischen auf GitHub geändert "
                f"({', '.join(changed)}). Bitte lass einen neuen Entwurf erstellen."
            )
    fields = {k: proposed[k] for k in (*_CONFLICT_FIELDS, "state_reason") if k in proposed}
    if "title" in fields:
        fields["title"] = check_title(fields["title"])
    return svc.update_issue(issue_number, **fields)


def _normalized(value):
    return sorted(value) if isinstance(value, list) else value


def is_retryable(e: GithubException, kind: Kind) -> bool:
    """
    Failures the user can fix and retry (login, permission grant, rate limit).
    A 5xx is only safe to retry for updates: GitHub may have created the issue
    or comment before failing, and a retry would duplicate it. Updates are
    protected by the conflict check.
    """
    if e.status in (401, 403, 429):
        return True
    return e.status >= 500 and kind == "update_issue"


def describe_github_error(e: GithubException) -> str:
    """Translate a GitHub API failure into a German, actionable message."""
    message = ""
    if isinstance(e.data, dict):
        message = e.data.get("message", "") or ""
    if e.status == 401:
        return "Deine GitHub-Anmeldung ist abgelaufen oder ungültig. Bitte melde dich erneut an."
    if e.status >= 500:
        return (
            f"GitHub hat mit einem Serverfehler ({e.status}) geantwortet. Bitte prüfe auf GitHub, "
            "ob die Änderung trotzdem übernommen wurde, bevor du es erneut versuchst."
        )
    if e.status == 403:
        if "rate limit" in message.lower():
            return "Das GitHub-API-Limit ist erreicht. Bitte später erneut versuchen."
        return (
            "Der GitHub App fehlt die Berechtigung „Issues: Lesen & Schreiben“ für dieses "
            "Repository, oder dein GitHub-Konto darf hier keine Issues bearbeiten. "
            "Ein Administrator muss die Berechtigung der App erweitern und die "
            "Installation aktualisieren."
        )
    if e.status in (404, 410):
        return "Repository oder Issue nicht gefunden – oder Issues sind in diesem Repository deaktiviert."
    if e.status == 422:
        return f"GitHub hat die Änderung abgelehnt: {message or 'ungültige Eingabe'}."
    return f"GitHub-Fehler ({e.status}): {message or 'unbekannt'}."
