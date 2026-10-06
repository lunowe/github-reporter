# app/services/issue_actions.py
"""
Issue drafts proposed by the chat agent and confirmed by the user.

The agent never writes to GitHub directly: its propose_* tools store a draft
here (status "pending"). Only an explicit apply by the owning user performs
the write — with that user's own GitHub token.

Lifecycle: pending → applying → applied | failed,  or  pending → rejected.
"pending → applying" is an atomic claim, so a double-click or a retried
request can never create the same issue twice. Failures the user can fix
(missing App permission, rate limit, GitHub outage) return the draft to
"pending" with the error attached, so it can be retried instead of re-drafted.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import anyio
from github import GithubException

from app.db import get_db
from app.services.github_service import GitHubService
from app.services.issue_writes import (
    IssueWriteError,
    Kind,
    check_body,
    body_is_replaceable,
    check_title,
    describe_github_error,
    execute,
    is_retryable,
)
from app.services.repo_access import get_authorized_repo
from app.services.token_resolver import resolve_github_token

logger = logging.getLogger(__name__)

# Drafts older than this can't be applied anymore (the snapshot is too stale).
DRAFT_MAX_AGE = timedelta(days=7)
# An "applying" claim older than this means the worker died mid-write.
APPLY_STALE_AFTER = timedelta(minutes=5)
# Drafts are deleted after this (chat cards then show "not found").
DRAFT_RETENTION = timedelta(days=90)


class IssueActionNotFound(Exception):
    pass


class IssueActionForbidden(Exception):
    pass


class IssueActionConflict(Exception):
    pass


class IssueActionInvalid(Exception):
    """The user's edits can't be applied as given; the draft stays pending."""


def _collection():
    return get_db().issue_actions


async def ensure_indexes() -> None:
    await _collection().create_index("action_id", unique=True)
    await _collection().create_index([("user_id", 1), ("created_at", -1)])
    await _collection().create_index(
        "created_at", expireAfterSeconds=int(DRAFT_RETENTION.total_seconds()),
    )


def read_only_reason(user: dict) -> Optional[str]:
    if user.get("auth_method", "github") != "github":
        return "viewer"
    if user.get("suspended"):
        return "suspended"
    return None


_READ_ONLY_MESSAGES = {
    "viewer": "Dein Konto hat nur Lesezugriff.",
    "suspended": "Dein Konto ist gesperrt.",
}


def can_write(user: dict) -> bool:
    """Only GitHub-authenticated, non-suspended users may write. Viewers act
    through their invitor's token and must never write in someone else's name."""
    return user.get("auth_method", "github") == "github" and not user.get("suspended")


async def create_draft(
    *,
    user_id: str,
    chat_id: Optional[str],
    repo: str,
    kind: Kind,
    proposed: dict,
    issue_number: Optional[int] = None,
    current: Optional[dict] = None,
) -> str:
    now = datetime.now(timezone.utc)
    action_id = f"ia_{uuid.uuid4().hex[:20]}"
    await _collection().insert_one({
        "action_id": action_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "repo": repo,
        "kind": kind,
        "issue_number": issue_number,
        "status": "pending",
        "proposed": proposed,
        "current": current,
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    })
    return action_id


async def get_action(action_id: str, user: dict) -> dict:
    doc = await _collection().find_one({"action_id": action_id, "user_id": str(user["_id"])})
    if not doc:
        raise IssueActionNotFound()
    return serialize(doc, user)


async def reject(action_id: str, user: dict) -> dict:
    user_id = str(user["_id"])
    doc = await _collection().find_one_and_update(
        {"action_id": action_id, "user_id": user_id, "status": "pending"},
        {"$set": {"status": "rejected", "updated_at": datetime.now(timezone.utc)}},
        return_document=True,
    )
    if not doc:
        await _raise_missing_or_conflict(action_id, user_id)
    return serialize(doc, user)


async def apply(
    action_id: str,
    user: dict,
    *,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> dict:
    """
    Perform a pending draft on GitHub, optionally with the user's last-minute
    edits to title/body. Everything that can be checked up front is checked
    before the claim, so a bad edit or an expired login leaves the draft
    pending. GitHub-side failures are returned in the action, not raised.
    """
    user_id = str(user["_id"])
    doc = await _collection().find_one({"action_id": action_id, "user_id": user_id})
    if not doc:
        raise IssueActionNotFound()
    if not can_write(user):
        raise IssueActionForbidden(_READ_ONLY_MESSAGES[read_only_reason(user)])
    if doc["status"] != "pending":
        await _raise_missing_or_conflict(action_id, user_id)
    if not await get_authorized_repo(user, doc["repo"]):
        raise IssueActionForbidden("Kein Zugriff (mehr) auf dieses Repository.")

    now = datetime.now(timezone.utc)
    if now - _aware(doc["created_at"]) > DRAFT_MAX_AGE:
        expired = await _collection().find_one_and_update(
            {"action_id": action_id, "user_id": user_id, "status": "pending"},
            {"$set": {
                "status": "failed",
                "error": "Der Entwurf ist abgelaufen. Bitte lass einen neuen erstellen.",
                "updated_at": now,
            }},
            return_document=True,
        )
        if not expired:
            await _raise_missing_or_conflict(action_id, user_id)
        return serialize(expired, user)

    proposed = dict(doc["proposed"])
    try:
        if title is not None and doc["kind"] != "comment":
            if doc["kind"] == "update_issue" and "title" not in proposed:
                raise IssueWriteError("Dieser Entwurf ändert den Titel nicht.")
            proposed["title"] = check_title(title)
        if body is not None:
            if doc["kind"] == "update_issue":
                if "body" not in proposed:
                    raise IssueWriteError("Dieser Entwurf ändert die Beschreibung nicht.")
                if not body_is_replaceable(doc.get("current") or {}):
                    raise IssueWriteError(
                        "Diese Beschreibung ist zu lang, um sie hier zu bearbeiten. "
                        "Übernimm den Entwurf unverändert oder bearbeite das Issue direkt auf GitHub."
                    )
            proposed["body"] = check_body(body)
            if doc["kind"] == "comment" and not proposed["body"].strip():
                raise IssueWriteError("Der Kommentar darf nicht leer sein.")
    except IssueWriteError as e:
        raise IssueActionInvalid(str(e)) from e

    # Raises HTTPException (expired login…) before anything is claimed.
    token = await resolve_github_token(user)

    claimed = await _collection().find_one_and_update(
        {"action_id": action_id, "user_id": user_id, "status": "pending"},
        {"$set": {"status": "applying", "updated_at": now}},
        return_document=True,
    )
    if not claimed:
        await _raise_missing_or_conflict(action_id, user_id)

    status, result, error = None, None, None
    try:
        def _work() -> dict:
            svc = GitHubService(token=token, repo_full_name=claimed["repo"])
            return execute(
                svc,
                kind=claimed["kind"],
                proposed=proposed,
                issue_number=claimed.get("issue_number"),
                current=claimed.get("current"),
            )

        result = await anyio.to_thread.run_sync(_work)
        status = "applied"
    except IssueWriteError as e:
        status, error = "failed", str(e)
    except GithubException as e:
        logger.warning("Issue action %s rejected by GitHub: %s %s", action_id, e.status, e.data)
        status = "pending" if is_retryable(e, claimed["kind"]) else "failed"
        error = describe_github_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("Issue action %s failed", action_id)
        status, error = "failed", f"Unerwarteter Fehler: {e}"
    finally:
        # status is None only on cancellation: the worker thread may still
        # complete the write, so leave "applying" and let serialize() report
        # the unknown outcome once the claim goes stale.
        if status is not None:
            await _finalise(action_id, status, result, error, proposed)
        else:
            logger.warning("Issue action %s cancelled mid-apply; outcome unknown", action_id)

    final = await _collection().find_one({"action_id": action_id})
    logger.info("Issue action %s (%s) → %s", action_id, claimed["kind"], final["status"])
    return serialize(final, user)


async def _finalise(action_id: str, status: str, result, error, proposed: dict) -> None:
    update = {"status": status, "result": result, "error": error,
              "updated_at": datetime.now(timezone.utc)}
    if status == "applied":
        update["proposed"] = proposed  # store what was actually written
    try:
        await _collection().update_one({"action_id": action_id}, {"$set": update})
    except Exception:
        logger.exception("Could not finalise issue action %s (status=%s)", action_id, status)
        raise


async def _raise_missing_or_conflict(action_id: str, user_id: str) -> None:
    doc = await _collection().find_one({"action_id": action_id, "user_id": user_id})
    if not doc:
        raise IssueActionNotFound()
    # Report the same effective status GET shows (stale claims, expiry).
    raise IssueActionConflict(f"Der Entwurf ist nicht mehr offen (Status: {serialize(doc, {})['status']}).")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def serialize(doc: dict, user: dict) -> dict:
    status = doc["status"]
    error = doc.get("error")
    updated_at = _aware(doc["updated_at"])
    # A claim that never finished: the worker died mid-write. We can't know
    # whether GitHub got the request, so say so instead of spinning forever.
    now = datetime.now(timezone.utc)
    if status == "applying" and now - _aware(doc["updated_at"]) > APPLY_STALE_AFTER:
        status = "failed"
        error = "Status unbekannt – die Übernahme wurde unterbrochen. Bitte auf GitHub prüfen."
    elif status == "pending" and now - _aware(doc["created_at"]) > DRAFT_MAX_AGE:
        status = "failed"
        error = "Der Entwurf ist abgelaufen. Bitte lass einen neuen erstellen."
        updated_at = _aware(doc["created_at"]) + DRAFT_MAX_AGE
    return {
        "action_id": doc["action_id"],
        "kind": doc["kind"],
        "repo": doc["repo"],
        "issue_number": doc.get("issue_number"),
        "status": status,
        "proposed": doc.get("proposed") or {},
        "current": _public_snapshot(doc.get("current")),
        "result": doc.get("result"),
        "error": error,
        "can_apply": status == "pending" and can_write(user),
        "read_only_reason": read_only_reason(user),
        "created_at": _aware(doc["created_at"]).isoformat(),
        "updated_at": updated_at.isoformat(),
    }


def _public_snapshot(current: Optional[dict]) -> Optional[dict]:
    if not current:
        return None
    keys = ("title", "body", "labels", "assignees", "state", "html_url")
    return {k: current.get(k) for k in keys}
