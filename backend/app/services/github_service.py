# app/services/github_service.py
"""
PyGithub wrapper – single class that every tool delegates to.
Returns plain dicts with smart truncation to stay within LLM context limits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from github import Github, Auth
from cachetools import TTLCache

from app.utils import trunc

logger = logging.getLogger(__name__)

# In-memory caches (per-process).  Keys = (repo, method, *params)
_commits_cache: TTLCache = TTLCache(maxsize=128, ttl=300)
_prs_cache: TTLCache = TTLCache(maxsize=128, ttl=120)
_issues_cache: TTLCache = TTLCache(maxsize=128, ttl=300)
_actions_cache: TTLCache = TTLCache(maxsize=64, ttl=120)
_summary_cache: TTLCache = TTLCache(maxsize=32, ttl=600)


class GitHubService:
    """Thin wrapper around PyGithub for a single repository."""

    def __init__(self, token: str, repo_full_name: str):
        self.github = Github(auth=Auth.Token(token))
        self.repo = self.github.get_repo(repo_full_name)
        self.repo_full_name = repo_full_name

    # ── Commits ─────────────────────────────────────────────────────────

    def get_recent_commits(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        author: Optional[str] = None,
        branch: str = "main",
        limit: int = 20,
    ) -> list[dict]:
        cache_key = (self.repo_full_name, "commits", str(since), str(until), author, branch, limit)
        if cache_key in _commits_cache:
            return _commits_cache[cache_key]

        kwargs: dict = {"sha": branch}
        if since:
            kwargs["since"] = since
        if until:
            kwargs["until"] = until

        commits_raw = self.repo.get_commits(**kwargs)
        result: list[dict] = []
        for c in commits_raw[:limit]:
            if author and c.author and c.author.login != author:
                continue
            result.append({
                "sha": c.sha[:8],
                "message": trunc(c.commit.message, 200),
                "author": c.author.login if c.author else c.commit.author.name,
                "date": c.commit.author.date.isoformat(),
                "url": c.html_url,
            })

        _commits_cache[cache_key] = result
        return result

    # ── Pull Requests ───────────────────────────────────────────────────

    def get_pull_requests(
        self,
        state: str = "open",
        limit: int = 20,
    ) -> list[dict]:
        cache_key = (self.repo_full_name, "prs", state, limit)
        if cache_key in _prs_cache:
            return _prs_cache[cache_key]

        prs = self.repo.get_pulls(state=state, sort="updated", direction="desc")
        result: list[dict] = []
        for pr in prs[:limit]:
            result.append({
                "number": pr.number,
                "title": trunc(pr.title, 120),
                "state": pr.state,
                "author": pr.user.login if pr.user else "unknown",
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "labels": [l.name for l in pr.labels],
                "draft": pr.draft,
                "mergeable": pr.mergeable,
                "review_comments": pr.review_comments,
                "url": pr.html_url,
            })

        _prs_cache[cache_key] = result
        return result

    def get_pr_detail(self, pr_number: int) -> dict:
        pr = self.repo.get_pull(pr_number)
        reviews = list(pr.get_reviews())
        files = list(pr.get_files())
        return {
            "number": pr.number,
            "title": pr.title,
            "body": trunc(pr.body, 500),
            "state": pr.state,
            "author": pr.user.login if pr.user else "unknown",
            "created_at": pr.created_at.isoformat(),
            "updated_at": pr.updated_at.isoformat(),
            "merged": pr.merged,
            "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
            "merged_by": pr.merged_by.login if pr.merged_by else None,
            "labels": [l.name for l in pr.labels],
            "draft": pr.draft,
            "mergeable": pr.mergeable,
            "additions": pr.additions,
            "deletions": pr.deletions,
            "changed_files": pr.changed_files,
            "files": [{"name": f.filename, "status": f.status, "changes": f.changes} for f in files[:30]],
            "reviews": [
                {"user": r.user.login, "state": r.state, "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None}
                for r in reviews
            ],
            "comments": pr.comments,
            "review_comments": pr.review_comments,
            "url": pr.html_url,
        }

    # ── Issues ──────────────────────────────────────────────────────────

    def get_issues(
        self,
        state: str = "open",
        labels: Optional[list[str]] = None,
        assignee: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        cache_key = (self.repo_full_name, "issues", state, str(labels), assignee, limit)
        if cache_key in _issues_cache:
            return _issues_cache[cache_key]

        kwargs: dict = {"state": state, "sort": "updated", "direction": "desc"}
        if labels:
            kwargs["labels"] = labels
        if assignee:
            kwargs["assignee"] = assignee

        issues_raw = self.repo.get_issues(**kwargs)
        result: list[dict] = []
        for issue in issues_raw[:limit]:
            # Skip pull requests (GitHub API returns them as issues too)
            if issue.pull_request:
                continue
            result.append({
                "number": issue.number,
                "title": trunc(issue.title, 120),
                "state": issue.state,
                "author": issue.user.login if issue.user else "unknown",
                "assignees": [a.login for a in issue.assignees],
                "labels": [l.name for l in issue.labels],
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
                "comments": issue.comments,
                "url": issue.html_url,
            })

        _issues_cache[cache_key] = result
        return result

    def get_issue_detail(self, issue_number: int) -> dict:
        issue = self.repo.get_issue(issue_number)
        comments = list(issue.get_comments())
        return {
            "number": issue.number,
            "title": issue.title,
            "body": trunc(issue.body, 500),
            "state": issue.state,
            "author": issue.user.login if issue.user else "unknown",
            "assignees": [a.login for a in issue.assignees],
            "labels": [l.name for l in issue.labels],
            "milestone": issue.milestone.title if issue.milestone else None,
            "created_at": issue.created_at.isoformat(),
            "updated_at": issue.updated_at.isoformat(),
            "closed_at": issue.closed_at.isoformat() if issue.closed_at else None,
            "comments_list": [
                {
                    "user": c.user.login,
                    "body": trunc(c.body, 300),
                    "created_at": c.created_at.isoformat(),
                }
                for c in comments[:20]
            ],
            "url": issue.html_url,
        }

    # ── Actions / Workflow Runs ─────────────────────────────────────────

    def get_workflow_runs(
        self,
        status: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        cache_key = (self.repo_full_name, "actions", status, limit)
        if cache_key in _actions_cache:
            return _actions_cache[cache_key]

        kwargs: dict = {}
        if status:
            kwargs["status"] = status

        runs = self.repo.get_workflow_runs(**kwargs)
        result: list[dict] = []
        for run in runs[:limit]:
            result.append({
                "id": run.id,
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "branch": run.head_branch,
                "event": run.event,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "url": run.html_url,
                "actor": run.actor.login if run.actor else "unknown",
            })

        _actions_cache[cache_key] = result
        return result

    # ── Repository Summary ──────────────────────────────────────────────

    def get_repo_summary(self) -> dict:
        cache_key = (self.repo_full_name, "summary")
        if cache_key in _summary_cache:
            return _summary_cache[cache_key]

        open_prs = self.repo.get_pulls(state="open")
        open_issues = self.repo.get_issues(state="open")
        # Filter out PRs from issue count
        issue_count = sum(1 for i in open_issues[:100] if not i.pull_request)

        branches = list(self.repo.get_branches())

        recent_runs = self.repo.get_workflow_runs()
        latest_run = None
        for run in recent_runs[:1]:
            latest_run = {
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "updated_at": run.updated_at.isoformat(),
            }

        last_commit = None
        for c in self.repo.get_commits()[:1]:
            last_commit = {
                "sha": c.sha[:8],
                "message": trunc(c.commit.message, 120),
                "author": c.author.login if c.author else c.commit.author.name,
                "date": c.commit.author.date.isoformat(),
            }

        result = {
            "repo": self.repo_full_name,
            "description": trunc(self.repo.description, 200),
            "default_branch": self.repo.default_branch,
            "open_prs": open_prs.totalCount,
            "open_issues": issue_count,
            "branch_count": len(branches),
            "branches": [b.name for b in branches[:20]],
            "last_commit": last_commit,
            "latest_ci_run": latest_run,
            "stars": self.repo.stargazers_count,
            "forks": self.repo.forks_count,
        }

        _summary_cache[cache_key] = result
        return result

    # ── Dashboard Details ─────────────────────────────────────────────────

    def get_commit_activity(self) -> list[dict]:
        """Weekly commit counts for the last year (52 weeks).
        Uses the GitHub Statistics API which may return None on first call
        (GitHub returns 202 while computing). We don't retry — just return empty."""
        try:
            # PyGithub's get_stats_commit_activity can block/retry internally.
            # Use the raw requester with a short timeout to avoid hanging.
            status, headers, data = self.repo._requester.requestJson(
                "GET",
                self.repo.url + "/stats/commit_activity",
            )
            if status == 202 or not data:
                # GitHub is still computing stats — return empty, will work next time
                return []
            return [
                {"week": entry["week"], "total": entry["total"]}
                for entry in data
            ]
        except Exception:
            return []

    def get_languages(self) -> dict:
        """Language breakdown in bytes."""
        try:
            return self.repo.get_languages()
        except Exception:
            return {}

    def get_top_contributors(self, limit: int = 8) -> list[dict]:
        """Top contributors by commit count."""
        try:
            contributors = self.repo.get_contributors()
            return [
                {
                    "login": c.login,
                    "avatar_url": c.avatar_url,
                    "contributions": c.contributions,
                }
                for c in contributors[:limit]
            ]
        except Exception:
            return []

    def get_recent_activity(self, limit: int = 8) -> list[dict]:
        """Recent repo events: PR merges, issue opens, pushes, releases."""
        try:
            events = self.repo.get_events()
            result: list[dict] = []
            for event in events[:50]:
                entry = _format_event(event)
                if entry:
                    result.append(entry)
                    if len(result) >= limit:
                        break
            return result
        except Exception:
            return []

    def get_dashboard_details(self) -> dict:
        """Fetch all dashboard detail data in one call."""
        return {
            "commit_activity": self.get_commit_activity(),
            "languages": self.get_languages(),
            "contributors": self.get_top_contributors(),
            "recent_activity": self.get_recent_activity(),
        }

    # ── File / Directory Browsing ─────────────────────────────────────────

    def browse_directory(
        self,
        path: str = "",
        ref: Optional[str] = None,
    ) -> list[dict]:
        """List files and directories at a given path."""
        ref = ref or self.repo.default_branch
        try:
            contents = self.repo.get_contents(path, ref=ref)
        except Exception as e:
            return [{"error": str(e)}]

        if not isinstance(contents, list):
            # Single file, not a directory
            return [{
                "type": "file",
                "name": contents.name,
                "path": contents.path,
                "size": contents.size,
            }]

        result: list[dict] = []
        for item in contents:
            entry: dict = {
                "type": item.type,  # "file" or "dir"
                "name": item.name,
                "path": item.path,
            }
            if item.type == "file":
                entry["size"] = item.size
            result.append(entry)

        # Sort: directories first, then files, alphabetically
        result.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"]))
        return result

    def read_file(
        self,
        path: str,
        ref: Optional[str] = None,
        start_line: int = 1,
        end_line: int = 300,
    ) -> dict:
        """Read the content of a file with optional line range."""
        ref = ref or self.repo.default_branch
        try:
            content_file = self.repo.get_contents(path, ref=ref)
        except Exception as e:
            return {"error": str(e)}

        if isinstance(content_file, list):
            return {"error": f"'{path}' ist ein Verzeichnis, keine Datei."}

        # Check for binary files
        if content_file.encoding != "base64" or content_file.size > 1_000_000:
            return {
                "path": path,
                "size": content_file.size,
                "error": "Datei zu groß oder binär – kann nicht angezeigt werden.",
            }

        try:
            decoded = content_file.decoded_content.decode("utf-8")
        except (UnicodeDecodeError, Exception):
            return {
                "path": path,
                "size": content_file.size,
                "error": "Binärdatei – kann nicht als Text angezeigt werden.",
            }

        lines = decoded.splitlines()
        total_lines = len(lines)

        # Clamp range
        start_line = max(1, start_line)
        end_line = min(end_line, total_lines)

        selected = lines[start_line - 1 : end_line]

        # Add line numbers
        numbered = "\n".join(
            f"{start_line + i:>4} | {line}"
            for i, line in enumerate(selected)
        )

        return {
            "path": path,
            "total_lines": total_lines,
            "showing": f"{start_line}-{end_line}",
            "content": numbered,
        }

    # ── Branch Comparison ──────────────────────────────────────────────

    def compare_branches(self, base: str, head: str) -> dict:
        """Compare two branches/commits and return the diff summary."""
        try:
            comparison = self.repo.compare(base, head)
        except Exception as e:
            return {"error": str(e)}

        files_changed: list[dict] = []
        for f in comparison.files[:50]:
            files_changed.append({
                "filename": f.filename,
                "status": f.status,  # added, removed, modified, renamed
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
            })

        return {
            "base": base,
            "head": head,
            "status": comparison.status,  # ahead, behind, diverged, identical
            "ahead_by": comparison.ahead_by,
            "behind_by": comparison.behind_by,
            "total_commits": comparison.total_commits,
            "commits": [
                {
                    "sha": c.sha[:8],
                    "message": trunc(c.commit.message, 120),
                    "author": c.author.login if c.author else c.commit.author.name,
                    "date": c.commit.author.date.isoformat(),
                }
                for c in comparison.commits[:30]
            ],
            "files_changed": len(comparison.files),
            "additions": sum(f.additions for f in comparison.files),
            "deletions": sum(f.deletions for f in comparison.files),
            "files": files_changed,
        }

    # ── Contributors ───────────────────────────────────────────────────

    def get_contributors(self, limit: int = 30) -> list[dict]:
        """List contributors sorted by number of contributions."""
        contributors = self.repo.get_contributors()
        result: list[dict] = []
        for c in contributors[:limit]:
            result.append({
                "login": c.login,
                "contributions": c.contributions,
                "avatar_url": c.avatar_url,
                "url": c.html_url,
            })
        return result

    # ── Code Search ────────────────────────────────────────────────────

    def search_code(
        self,
        query: str,
        path: Optional[str] = None,
        extension: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search for code in the repository using the GitHub Search API."""
        # Build the search query: the search term + repo qualifier
        search_q = f"{query} repo:{self.repo_full_name}"
        if path:
            search_q += f" path:{path}"
        if extension:
            search_q += f" extension:{extension}"

        try:
            results = self.github.search_code(
                search_q,
                text_match=True,
            )
        except Exception as e:
            return [{"error": str(e)}]

        items: list[dict] = []
        for item in results[:limit]:
            # Each result has matched text fragments
            fragments: list[str] = []
            if hasattr(item, "text_matches") and item.text_matches:
                for match in item.text_matches[:3]:
                    fragment = match.get("fragment", "")
                    if fragment:
                        fragments.append(trunc(fragment, 200))

            items.append({
                "path": item.path,
                "name": item.name,
                "url": item.html_url,
                "fragments": fragments,
            })

        return items

    # ── Rate limit info ─────────────────────────────────────────────────

    def get_rate_limit_info(self) -> dict:
        rl = self.github.get_rate_limit()
        return {
            "remaining": rl.core.remaining,
            "limit": rl.core.limit,
            "resets_at": rl.core.reset.isoformat(),
        }


# ── Helpers ────────────────────────────────────────────────────────────

def _format_event(event) -> dict | None:
    """Format a GitHub event into a dashboard-friendly dict. Returns None for uninteresting events."""
    t = event.type
    payload = event.payload
    actor = event.actor.login if event.actor else "unknown"
    created = event.created_at.isoformat() if event.created_at else ""

    if t == "PushEvent":
        commits = payload.get("commits", [])
        count = len(commits)
        msg = commits[0]["message"].split("\n")[0] if commits else ""
        return {
            "type": "push",
            "actor": actor,
            "description": f"{count} commit{'s' if count != 1 else ''}: {msg[:80]}",
            "created_at": created,
        }
    elif t == "PullRequestEvent":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        merged = pr.get("merged", False)
        label = "merged" if merged and action == "closed" else action
        return {
            "type": "pr",
            "actor": actor,
            "description": f"PR #{pr.get('number', '?')} {label}: {pr.get('title', '')[:80]}",
            "created_at": created,
        }
    elif t == "IssuesEvent":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        return {
            "type": "issue",
            "actor": actor,
            "description": f"Issue #{issue.get('number', '?')} {action}: {issue.get('title', '')[:80]}",
            "created_at": created,
        }
    elif t == "ReleaseEvent":
        release = payload.get("release", {})
        return {
            "type": "release",
            "actor": actor,
            "description": f"Release {release.get('tag_name', '?')}: {release.get('name', '')[:80]}",
            "created_at": created,
        }
    elif t == "CreateEvent":
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        if ref_type == "branch":
            return {
                "type": "branch",
                "actor": actor,
                "description": f"Branch erstellt: {ref}",
                "created_at": created,
            }
    return None
