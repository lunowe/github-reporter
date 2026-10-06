"""
Issue drafts are the only path by which the chat agent writes to GitHub, so
the guarantees here matter: only the owner can apply, viewers can never write,
a draft is applied at most once, and edits made on GitHub meanwhile are not
overwritten.

Mongo is mongomock; GitHub is a fake that records writes.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.services import issue_actions
from fastapi import HTTPException
from github import GithubException

from app.services.issue_actions import (
    IssueActionConflict,
    IssueActionForbidden,
    IssueActionInvalid,
    IssueActionNotFound,
)

OWNER = {"_id": "owner-1", "auth_method": "github"}
OTHER = {"_id": "other-2", "auth_method": "github"}
VIEWER = {"_id": "owner-1", "auth_method": "email"}  # same id: role alone must block


class FakeGitHub:
    """Stands in for GitHubService; one shared issue store per test."""

    issues: dict[int, dict] = {}
    writes: list[tuple] = []
    delay = 0.0
    fail_with: GithubException | None = None  # raised by the next write
    drops_labels = False  # simulate a user without triage rights

    def __init__(self, token: str, repo_full_name: str):
        self.repo_full_name = repo_full_name

    def get_issue_snapshot(self, n):
        return dict(self.issues[n], number=n, html_url=f"https://gh/{n}", is_pull_request=False)

    def create_issue(self, title, body="", labels=None, assignees=None):
        import time
        time.sleep(self.delay)
        if FakeGitHub.fail_with:
            e, FakeGitHub.fail_with = FakeGitHub.fail_with, None
            raise e
        n = max(self.issues, default=0) + 1
        labels = [] if self.drops_labels else (labels or [])
        self.issues[n] = {"title": title, "body": body, "labels": labels,
                          "assignees": assignees or [], "state": "open"}
        self.writes.append(("create", n))
        return {"issue_number": n, "html_url": f"https://gh/{n}",
                "labels": labels, "assignees": assignees or []}

    def update_issue(self, n, **fields):
        self.issues[n].update({k: v for k, v in fields.items() if k != "state_reason"})
        self.writes.append(("update", n, fields))
        return {"issue_number": n, "html_url": f"https://gh/{n}"}

    def add_issue_comment(self, n, body):
        self.writes.append(("comment", n, body))
        return {"issue_number": n, "html_url": f"https://gh/{n}", "comment_url": f"https://gh/{n}#c"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    db = AsyncMongoMockClient()["test"]
    monkeypatch.setattr(issue_actions, "get_db", lambda: db)
    FakeGitHub.issues = {7: {"title": "Old", "body": "Body", "labels": ["bug"],
                             "assignees": [], "state": "open"}}
    FakeGitHub.writes = []
    FakeGitHub.delay = 0.0
    FakeGitHub.fail_with = None
    FakeGitHub.drops_labels = False
    monkeypatch.setattr(issue_actions, "GitHubService", FakeGitHub)

    async def token(user):
        return "tok"

    async def authorized(user, repo):
        return {"repo_full_name": repo} if repo == "acme/app" else None

    monkeypatch.setattr(issue_actions, "resolve_github_token", token)
    monkeypatch.setattr(issue_actions, "get_authorized_repo", authorized)
    return db


async def _create_draft(**overrides):
    draft = dict(user_id="owner-1", chat_id="c1", repo="acme/app", kind="create_issue",
                 proposed={"title": "New", "body": "Hello"})
    draft.update(overrides)
    return await issue_actions.create_draft(**draft)


async def test_owner_applies_create_with_edits():
    action_id = await _create_draft()
    result = await issue_actions.apply(action_id, OWNER, title="Edited", body="Edited body")
    assert result["status"] == "applied"
    assert result["result"]["issue_number"] == 8
    assert FakeGitHub.issues[8]["title"] == "Edited"
    assert result["proposed"]["title"] == "Edited"  # stored what was actually written


async def test_other_user_cannot_see_or_apply():
    action_id = await _create_draft()
    with pytest.raises(IssueActionNotFound):
        await issue_actions.get_action(action_id, OTHER)
    with pytest.raises(IssueActionNotFound):
        await issue_actions.apply(action_id, OTHER)
    with pytest.raises(IssueActionNotFound):
        await issue_actions.reject(action_id, OTHER)
    assert FakeGitHub.writes == []


async def test_viewer_cannot_apply_and_sees_read_only():
    action_id = await _create_draft()
    with pytest.raises(IssueActionForbidden):
        await issue_actions.apply(action_id, VIEWER)
    assert (await issue_actions.get_action(action_id, VIEWER))["can_apply"] is False
    assert FakeGitHub.writes == []


async def test_suspended_user_cannot_apply():
    action_id = await _create_draft()
    with pytest.raises(IssueActionForbidden):
        await issue_actions.apply(action_id, {**OWNER, "suspended": True})
    assert FakeGitHub.writes == []


async def test_revoked_repo_access_blocks_apply():
    action_id = await _create_draft(repo="acme/removed")
    with pytest.raises(IssueActionForbidden):
        await issue_actions.apply(action_id, OWNER)
    assert FakeGitHub.writes == []


async def test_concurrent_applies_write_once():
    FakeGitHub.delay = 0.05
    action_id = await _create_draft()
    results = await asyncio.gather(
        *(issue_actions.apply(action_id, OWNER) for _ in range(5)),
        return_exceptions=True,
    )
    applied = [r for r in results if isinstance(r, dict) and r["status"] == "applied"]
    conflicts = [r for r in results if isinstance(r, IssueActionConflict)]
    assert len(applied) == 1 and len(conflicts) == 4
    assert [w for w in FakeGitHub.writes if w[0] == "create"] == [("create", 8)]


async def test_cannot_apply_after_reject_or_reject_after_apply():
    rejected = await _create_draft()
    assert (await issue_actions.reject(rejected, OWNER))["status"] == "rejected"
    with pytest.raises(IssueActionConflict):
        await issue_actions.apply(rejected, OWNER)

    applied = await _create_draft()
    await issue_actions.apply(applied, OWNER)
    with pytest.raises(IssueActionConflict):
        await issue_actions.reject(applied, OWNER)
    assert len(FakeGitHub.writes) == 1


async def test_update_refuses_when_issue_changed_on_github():
    current = {"title": "Old", "body": "Body", "labels": ["bug"], "assignees": [], "state": "open"}
    action_id = await _create_draft(kind="update_issue", issue_number=7,
                                    proposed={"body": "New body"}, current=current)
    FakeGitHub.issues[7]["body"] = "Someone else edited this"
    result = await issue_actions.apply(action_id, OWNER)
    assert result["status"] == "failed"
    assert "inzwischen" in result["error"]
    assert FakeGitHub.issues[7]["body"] == "Someone else edited this"
    assert FakeGitHub.writes == []


async def test_update_ignores_changes_to_untouched_fields():
    current = {"title": "Old", "body": "Body", "labels": ["bug"], "assignees": [], "state": "open"}
    action_id = await _create_draft(kind="update_issue", issue_number=7,
                                    proposed={"state": "closed", "state_reason": "completed"},
                                    current=current)
    FakeGitHub.issues[7]["body"] = "Edited meanwhile, but we only close"
    result = await issue_actions.apply(action_id, OWNER)
    assert result["status"] == "applied"
    assert FakeGitHub.issues[7]["state"] == "closed"
    assert FakeGitHub.issues[7]["body"] == "Edited meanwhile, but we only close"


async def test_comment_ignores_title_override():
    action_id = await _create_draft(kind="comment", issue_number=7, proposed={"body": "Hi"},
                                    current={"title": "Old"})
    result = await issue_actions.apply(action_id, OWNER, title="ignored", body="Edited comment")
    assert result["status"] == "applied"
    assert FakeGitHub.writes == [("comment", 7, "Edited comment")]


async def test_expired_draft_is_not_applied(env):
    action_id = await _create_draft()
    old = datetime.now(timezone.utc) - timedelta(days=8)
    await env.issue_actions.update_one({"action_id": action_id}, {"$set": {"created_at": old}})
    result = await issue_actions.apply(action_id, OWNER)
    assert result["status"] == "failed" and "abgelaufen" in result["error"]
    assert FakeGitHub.writes == []


async def test_invalid_edit_is_rejected_and_draft_stays_pending():
    action_id = await _create_draft()
    with pytest.raises(IssueActionInvalid):
        await issue_actions.apply(action_id, OWNER, title="   ")
    assert (await issue_actions.get_action(action_id, OWNER))["status"] == "pending"
    assert FakeGitHub.writes == []


async def test_missing_permission_keeps_draft_retryable():
    action_id = await _create_draft()
    FakeGitHub.fail_with = GithubException(403, {"message": "Resource not accessible by integration"}, None)
    first = await issue_actions.apply(action_id, OWNER)
    assert first["status"] == "pending" and "Berechtigung" in first["error"]
    assert first["can_apply"] is True
    second = await issue_actions.apply(action_id, OWNER)  # after the admin granted access
    assert second["status"] == "applied" and second["error"] is None
    assert len(FakeGitHub.writes) == 1


async def test_validation_error_from_github_is_terminal():
    action_id = await _create_draft()
    FakeGitHub.fail_with = GithubException(422, {"message": "Validation Failed"}, None)
    result = await issue_actions.apply(action_id, OWNER)
    assert result["status"] == "failed" and result["can_apply"] is False


async def test_expired_login_leaves_draft_pending(monkeypatch):
    async def expired(user):
        raise HTTPException(status_code=401, detail="Bitte erneut anmelden.")

    monkeypatch.setattr(issue_actions, "resolve_github_token", expired)
    action_id = await _create_draft()
    with pytest.raises(HTTPException):
        await issue_actions.apply(action_id, OWNER)
    assert (await issue_actions.get_action(action_id, OWNER))["status"] == "pending"


async def test_silently_dropped_labels_are_reported():
    FakeGitHub.drops_labels = True
    action_id = await _create_draft(proposed={"title": "New", "labels": ["bug"]})
    result = await issue_actions.apply(action_id, OWNER)
    assert result["status"] == "applied"
    assert "bug" in result["result"]["warning"]


async def test_stale_applying_claim_reports_unknown(env):
    action_id = await _create_draft()
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    await env.issue_actions.update_one(
        {"action_id": action_id}, {"$set": {"status": "applying", "updated_at": stale}},
    )
    view = await issue_actions.get_action(action_id, OWNER)
    assert view["status"] == "failed" and view["can_apply"] is False


async def test_apply_edits_cannot_touch_fields_the_draft_does_not_change():
    current = {"title": "Old", "body": "Body", "labels": ["bug"], "assignees": [], "state": "open"}
    action_id = await _create_draft(kind="update_issue", issue_number=7,
                                    proposed={"labels": []}, current=current)
    for edits in ({"title": "Injected"}, {"body": "Injected"}):
        with pytest.raises(IssueActionInvalid):
            await issue_actions.apply(action_id, OWNER, **edits)
    assert FakeGitHub.writes == []


async def test_apply_edit_cannot_replace_a_long_body():
    long_body = "x" * 25_000
    current = {"title": "Old", "body": long_body, "labels": [], "assignees": [], "state": "open"}
    FakeGitHub.issues[7]["body"] = long_body
    action_id = await _create_draft(kind="update_issue", issue_number=7,
                                    proposed={"body": long_body + "\n\nNachtrag"}, current=current)
    with pytest.raises(IssueActionInvalid):
        await issue_actions.apply(action_id, OWNER, body="short")
    assert (await issue_actions.apply(action_id, OWNER))["status"] == "applied"


async def test_expired_draft_reads_as_expired_before_apply(env):
    action_id = await _create_draft()
    old = datetime.now(timezone.utc) - timedelta(days=8)
    await env.issue_actions.update_one({"action_id": action_id}, {"$set": {"created_at": old}})
    view = await issue_actions.get_action(action_id, OWNER)
    assert view["status"] == "failed" and view["can_apply"] is False


async def test_read_only_reason():
    action_id = await _create_draft()
    assert (await issue_actions.get_action(action_id, OWNER))["read_only_reason"] is None
    assert (await issue_actions.get_action(action_id, VIEWER))["read_only_reason"] == "viewer"
    suspended = {**OWNER, "suspended": True}
    assert (await issue_actions.get_action(action_id, suspended))["read_only_reason"] == "suspended"


async def test_server_error_on_create_is_not_retryable():
    """GitHub may have created the issue before answering 502 — a retry could duplicate it."""
    action_id = await _create_draft()
    FakeGitHub.fail_with = GithubException(502, {"message": "Bad Gateway"}, None)
    result = await issue_actions.apply(action_id, OWNER)
    assert result["status"] == "failed" and "prüfe auf GitHub" in result["error"]


async def test_server_error_on_update_stays_retryable():
    current = {"title": "Old", "body": "Body", "labels": ["bug"], "assignees": [], "state": "open"}
    action_id = await _create_draft(kind="update_issue", issue_number=7,
                                    proposed={"title": "New"}, current=current)

    def boom(self, n, **fields):
        raise GithubException(503, {"message": "Unavailable"}, None)

    original = FakeGitHub.update_issue
    FakeGitHub.update_issue = boom
    try:
        assert (await issue_actions.apply(action_id, OWNER))["status"] == "pending"
    finally:
        FakeGitHub.update_issue = original
    assert (await issue_actions.apply(action_id, OWNER))["status"] == "applied"
