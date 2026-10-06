"""Rules for turning an agent's requested edit into a concrete change set."""

import pytest

from app.services.issue_writes import IssueWriteError, build_create, build_update


class FakeRepo:
    labels = ["bug", "Feature", "help wanted"]
    assignable = {"alice", "bob"}

    def __init__(self, issue=None, is_pr=False):
        self.issue = issue or {"title": "T", "body": "Body", "labels": ["bug"],
                               "assignees": ["alice"], "state": "open"}
        self.is_pr = is_pr

    def get_issue_snapshot(self, n):
        return dict(self.issue, number=n, html_url="u", is_pull_request=self.is_pr)

    def get_label_names(self):
        return self.labels

    def is_assignable(self, login):
        return login in self.assignable


def test_labels_resolve_case_insensitively_and_unknown_ones_list_alternatives():
    assert build_create(FakeRepo(), title="x", labels=["feature", "BUG"])["labels"] == ["Feature", "bug"]
    with pytest.raises(IssueWriteError, match="Verfügbare Labels: bug, Feature"):
        build_create(FakeRepo(), title="x", labels=["urgent"])


def test_update_merges_label_and_assignee_changes_into_full_sets():
    proposed, current = build_update(
        FakeRepo(), issue_number=1,
        add_labels=["feature"], remove_labels=["Bug"],
        add_assignees=["@bob"], remove_assignees=["ALICE"],
    )
    assert proposed == {"labels": ["Feature"], "assignees": ["bob"]}
    assert current["labels"] == ["bug"]


def test_update_only_includes_fields_that_change():
    proposed, _ = build_update(FakeRepo(), issue_number=1, title="T", body="Body", state="closed")
    assert proposed == {"state": "closed", "state_reason": "completed"}


def test_reopen_sets_reason_and_noop_is_rejected():
    closed = {"title": "T", "body": "", "labels": [], "assignees": [], "state": "closed"}
    proposed, _ = build_update(FakeRepo(closed), issue_number=1, state="open")
    assert proposed == {"state": "open", "state_reason": "reopened"}
    with pytest.raises(IssueWriteError, match="Keine Änderung"):
        build_update(FakeRepo(), issue_number=1, add_labels=["bug"])


def test_append_keeps_existing_body():
    proposed, _ = build_update(FakeRepo(), issue_number=1, append_to_body="Update: done")
    assert proposed["body"] == "Body\n\nUpdate: done"
    with pytest.raises(IssueWriteError):
        build_update(FakeRepo(), issue_number=1, body="x", append_to_body="y")


def test_pull_requests_and_unassignable_users_are_refused():
    with pytest.raises(IssueWriteError, match="Pull Request"):
        build_update(FakeRepo(is_pr=True), issue_number=1, title="New")
    with pytest.raises(IssueWriteError, match="mallory"):
        build_create(FakeRepo(), title="x", assignees=["mallory"])


def test_removing_a_label_the_repo_does_not_define_is_a_no_op():
    proposed, _ = build_update(FakeRepo(), issue_number=1, remove_labels=["wontfix"], title="New")
    assert proposed == {"title": "New"}


def test_long_body_cannot_be_replaced_but_can_be_appended():
    """Regression: the agent sees only the first 20k chars; replacing a longer
    body silently deleted everything after that on GitHub."""
    long_issue = {"title": "T", "body": "x" * 25_000, "labels": [], "assignees": [], "state": "open"}
    with pytest.raises(IssueWriteError, match="nicht vollständig"):
        build_update(FakeRepo(long_issue), issue_number=1, body="x" * 19_999 + " fixed")
    proposed, _ = build_update(FakeRepo(long_issue), issue_number=1, append_to_body="Nachtrag")
    assert proposed["body"].startswith("x" * 25_000) and proposed["body"].endswith("Nachtrag")


def test_zero_width_only_title_is_empty():
    with pytest.raises(IssueWriteError, match="leer"):
        build_create(FakeRepo(), title="​​ ﻿")


@pytest.mark.parametrize("title", ["ㅤ", "­", "⠀ ᠎", "​"])
def test_blank_looking_titles_are_empty(title):
    with pytest.raises(IssueWriteError, match="leer"):
        build_create(FakeRepo(), title=title)


def test_whitespace_only_append_is_no_change():
    with pytest.raises(IssueWriteError, match="Keine Änderung"):
        build_update(FakeRepo(), issue_number=1, append_to_body="   \n ")
