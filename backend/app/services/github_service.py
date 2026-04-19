# app/services/github_service.py
"""
PyGithub wrapper – single class that every tool delegates to.
Returns plain dicts with smart truncation to stay within LLM context limits.
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from github import Github, Auth, GithubRetry
from cachetools import TTLCache
from urllib3 import Retry

from app.utils import trunc

logger = logging.getLogger(__name__)

# In-memory caches (per-process).  Keys = (repo, method, *params)
_commits_cache: TTLCache = TTLCache(maxsize=128, ttl=300)
_prs_cache: TTLCache = TTLCache(maxsize=128, ttl=120)
_issues_cache: TTLCache = TTLCache(maxsize=128, ttl=300)
_actions_cache: TTLCache = TTLCache(maxsize=64, ttl=120)
_summary_cache: TTLCache = TTLCache(maxsize=32, ttl=600)
_packages_cache: TTLCache = TTLCache(maxsize=64, ttl=300)
_package_versions_cache: TTLCache = TTLCache(maxsize=128, ttl=300)

GITHUB_API_BASE = "https://api.github.com"


class GitHubService:
    """Thin wrapper around PyGithub for a single repository."""

    def __init__(self, token: str, repo_full_name: str):
        # Use a conservative retry policy: retry on server errors only,
        # NOT on 403 (which PyGithub misinterprets as rate-limiting when
        # it's actually a permissions error — causing ~40min backoffs).
        retry = GithubRetry(
            total=3,
            status_forcelist=[500, 502, 503, 504],
            backoff_factor=0.5,
        )
        self.github = Github(auth=Auth.Token(token), retry=retry)
        self.repo = self.github.get_repo(repo_full_name)
        self.repo_full_name = repo_full_name
        # Kept for direct REST calls (GHCR / Packages API aren't covered by PyGithub)
        self._token = token

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
            status, headers, data = self.repo._requester.requestJson(
                "GET",
                self.repo.url + "/stats/commit_activity",
            )
            if status in (202, 403) or not data:
                # 202 = GitHub is still computing stats
                # 403 = permission denied (don't retry, just return empty)
                return []
            return [
                {"week": entry["week"], "total": entry["total"]}
                for entry in data
            ]
        except Exception as e:
            logger.debug("get_commit_activity failed: %s", e)
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
        # NOTE: `results` is a PyGithub PaginatedList. Slicing it (results[:limit])
        # can raise IndexError because GitHub's code-search total_count often
        # overstates the number of retrievable items, and PyGithub trusts that
        # count when paging. Iterate with a counter and swallow the pagination
        # error so we return whatever we did manage to fetch.
        try:
            for item in results:
                if len(items) >= limit:
                    break

                fragments: list[str] = []
                if hasattr(item, "text_matches") and item.text_matches:
                    for match in item.text_matches[:3]:
                        fragment = match.get("fragment", "") if isinstance(match, dict) else ""
                        if fragment:
                            fragments.append(trunc(fragment, 200))

                items.append({
                    "path": item.path,
                    "name": item.name,
                    "url": item.html_url,
                    "fragments": fragments,
                })
        except IndexError:
            # PyGithub tripped over an inconsistent total_count / empty page.
            # Return whatever we collected so far rather than failing the tool.
            pass
        except Exception as e:
            if not items:
                return [{"error": str(e)}]

        return items

    # ── GHCR / Container Packages ───────────────────────────────────────
    #
    # The Packages REST API is NOT wrapped by PyGithub (only partial support),
    # so we call it directly with httpx using the same PAT. Requires the
    # 'read:packages' scope on classic PATs, or 'packages:read' on fine-grained
    # tokens. For private packages the token additionally needs access to the
    # publishing repo.

    def _gh_request_json(
        self,
        path: str,
        params: Optional[dict] = None,
    ) -> tuple[int, dict | list | None]:
        """Make a direct GitHub REST API GET call. Returns (status, json-or-None)."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-reporter",
        }
        url = f"{GITHUB_API_BASE}{path}"
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(url, headers=headers, params=params)
            if r.status_code >= 400:
                logger.debug("GitHub API %s returned %s: %s", path, r.status_code, r.text[:200])
                return r.status_code, None
            return r.status_code, r.json()
        except Exception as e:
            logger.warning("GitHub API call failed for %s: %s", path, e)
            return 599, None

    @property
    def _owner(self) -> str:
        """Owner (user or org) login from repo_full_name."""
        return self.repo_full_name.split("/", 1)[0]

    @property
    def _owner_path_segment(self) -> str:
        """'orgs' or 'users' for use in the REST URL path."""
        # PyGithub exposes owner.type as 'User' or 'Organization'
        return "orgs" if self.repo.owner.type == "Organization" else "users"

    def list_container_packages(self, only_this_repo: bool = True) -> list[dict]:
        """List all container packages owned by the repo's owner.

        When ``only_this_repo`` is True (default), filter to packages whose
        ``repository.full_name`` matches this repo. Set to False to see every
        image the org/user publishes on GHCR.
        """
        cache_key = (self.repo_full_name, "packages", only_this_repo)
        if cache_key in _packages_cache:
            return _packages_cache[cache_key]

        status, data = self._gh_request_json(
            f"/{self._owner_path_segment}/{self._owner}/packages",
            params={"package_type": "container", "per_page": 100},
        )
        if status == 404:
            logger.info("No container packages visible for %s (404)", self._owner)
            _packages_cache[cache_key] = []
            return []
        if status != 200 or not isinstance(data, list):
            return []

        owner_login = self._owner
        result: list[dict] = []
        for pkg in data:
            repo_info = pkg.get("repository") or {}
            linked_repo = repo_info.get("full_name")
            if only_this_repo and linked_repo and linked_repo != self.repo_full_name:
                continue
            # If only_this_repo=True and the package has no linked repo, keep it
            # too — user-published images sometimes lack that link but may still
            # belong to the project.
            pkg_owner = (pkg.get("owner") or {}).get("login") or owner_login
            pkg_name = pkg.get("name") or ""
            result.append({
                "name": pkg_name,
                "owner": pkg_owner,
                "visibility": pkg.get("visibility"),
                "version_count": pkg.get("version_count"),
                "linked_repo": linked_repo,
                "ghcr_ref": f"ghcr.io/{pkg_owner.lower()}/{pkg_name}",
                "html_url": pkg.get("html_url"),
                "created_at": pkg.get("created_at"),
                "updated_at": pkg.get("updated_at"),
            })

        _packages_cache[cache_key] = result
        return result

    def get_container_image_tags(
        self,
        package_name: str,
        limit: int = 30,
    ) -> list[dict]:
        """List versions (= immutable pushes, each with 0..N tags) of a container image.

        Each version has a SHA256 digest (``digest``) and may have multiple tags
        pointing at it. Untagged versions appear with an empty ``tags`` list.
        """
        limit = max(1, min(limit, 100))
        cache_key = (self.repo_full_name, "package_versions", package_name, limit)
        if cache_key in _package_versions_cache:
            return _package_versions_cache[cache_key]

        # Package names may contain slashes (e.g. 'backend/api'); encode them.
        safe_name = urllib.parse.quote(package_name, safe="")
        status, data = self._gh_request_json(
            f"/{self._owner_path_segment}/{self._owner}"
            f"/packages/container/{safe_name}/versions",
            params={"per_page": limit},
        )
        if status != 200 or not isinstance(data, list):
            return []

        result: list[dict] = []
        for v in data[:limit]:
            meta = v.get("metadata") or {}
            container = meta.get("container") or {}
            result.append({
                "version_id": v.get("id"),
                "digest": v.get("name"),  # 'sha256:...'
                "tags": container.get("tags") or [],
                "created_at": v.get("created_at"),
                "updated_at": v.get("updated_at"),
                "html_url": v.get("html_url"),
            })

        _package_versions_cache[cache_key] = result
        return result

    def get_container_image_details(
        self,
        package_name: str,
        tag: Optional[str] = None,
    ) -> dict:
        """Detailed info on a container image, optionally narrowed to a specific tag."""
        safe_name = urllib.parse.quote(package_name, safe="")
        status, pkg = self._gh_request_json(
            f"/{self._owner_path_segment}/{self._owner}"
            f"/packages/container/{safe_name}",
        )
        if status == 404 or not isinstance(pkg, dict):
            return {
                "error": f"Container-Image '{package_name}' nicht gefunden "
                         f"(Status {status}). Prüfe Name und Token-Scope 'read:packages'."
            }
        if status != 200:
            return {"error": f"GitHub Packages API Status {status} für '{package_name}'."}

        # Pull up to 100 versions so we can search tags / compute summaries.
        versions = self.get_container_image_tags(package_name, limit=100)
        owner_login = self._owner.lower()
        ghcr_base = f"ghcr.io/{owner_login}/{package_name}"
        linked_repo = (pkg.get("repository") or {}).get("full_name")

        if tag:
            matching = [v for v in versions if tag in (v.get("tags") or [])]
            if not matching:
                all_tags = sorted({t for v in versions for t in (v.get("tags") or [])})
                return {
                    "error": f"Tag '{tag}' für Image '{package_name}' nicht gefunden.",
                    "available_tags_sample": all_tags[:30],
                }
            return {
                "package": package_name,
                "ghcr_ref": f"{ghcr_base}:{tag}",
                "visibility": pkg.get("visibility"),
                "linked_repo": linked_repo,
                "total_versions": pkg.get("version_count"),
                "tag": tag,
                "version": matching[0],
            }

        # No tag → summary across all versions
        all_tags = sorted({t for v in versions for t in (v.get("tags") or [])})
        latest = versions[0] if versions else None
        return {
            "package": package_name,
            "ghcr_ref": ghcr_base,
            "visibility": pkg.get("visibility"),
            "linked_repo": linked_repo,
            "total_versions": pkg.get("version_count"),
            "latest_version": latest,
            "tags_sample": all_tags[:50],
            "tags_total": len(all_tags),
            "created_at": pkg.get("created_at"),
            "updated_at": pkg.get("updated_at"),
        }

    def find_image_for_commit(
        self,
        commit_sha: str,
        package_name: Optional[str] = None,
    ) -> dict:
        """Find container versions whose tags reference the given commit SHA.

        Matches common tagging patterns produced by docker/metadata-action
        and similar CI workflows: ``sha-<shortsha>``, ``main-<shortsha>``,
        bare ``<shortsha>``, and full-SHA variants.

        Also returns the check-runs recorded on that commit so the agent can
        explain whether the build that would have published an image actually
        ran + succeeded.
        """
        sha = (commit_sha or "").strip().lower()
        if len(sha) < 7:
            return {"error": "Commit-SHA muss mindestens 7 Zeichen lang sein."}
        short = sha[:7]

        # Decide which packages to scan.
        if package_name:
            packages_to_search = [package_name]
        else:
            pkgs = self.list_container_packages(only_this_repo=True)
            packages_to_search = [p["name"] for p in pkgs]

        owner_login = self._owner.lower()
        matches: list[dict] = []
        for pkg_name in packages_to_search:
            versions = self.get_container_image_tags(pkg_name, limit=100)
            for v in versions:
                tags = v.get("tags") or []
                hit_tag: Optional[str] = None
                for t in tags:
                    tl = t.lower()
                    if sha in tl or short in tl:
                        hit_tag = t
                        break
                if hit_tag:
                    matches.append({
                        "package": pkg_name,
                        "matched_tag": hit_tag,
                        "all_tags": tags,
                        "digest": v.get("digest"),
                        "created_at": v.get("created_at"),
                        "ghcr_ref": f"ghcr.io/{owner_login}/{pkg_name}:{hit_tag}",
                    })

        # Context: check-runs on that commit (which CI jobs ran, did they pass).
        status, runs_data = self._gh_request_json(
            f"/repos/{self.repo_full_name}/commits/{sha}/check-runs",
            params={"per_page": 20},
        )
        check_runs: list[dict] = []
        if status == 200 and isinstance(runs_data, dict):
            for cr in (runs_data.get("check_runs") or [])[:20]:
                check_runs.append({
                    "name": cr.get("name"),
                    "status": cr.get("status"),
                    "conclusion": cr.get("conclusion"),
                    "started_at": cr.get("started_at"),
                    "completed_at": cr.get("completed_at"),
                    "url": cr.get("html_url"),
                })

        return {
            "commit_sha": sha,
            "short_sha": short,
            "searched_packages": packages_to_search,
            "match_count": len(matches),
            "matches": matches,
            "check_runs": check_runs,
        }

    # ── Rate limit info ─────────────────────────────────────────────────

    def get_rate_limit_info(self) -> dict:
        """Return a detailed breakdown of the authenticated user's API quota.

        Includes the three buckets GitHub reports separately (core, search,
        graphql) plus a fetched_at timestamp for the UI's countdown logic.
        """
        rl = self.github.get_rate_limit()
        return _format_rate_limit(rl)


def fetch_rate_limit(token: str) -> dict:
    """Fetch rate limit info for a token without needing a repo handle.

    The GitHub /rate_limit endpoint does NOT consume API quota itself, so
    this is cheap to poll. Blocking — call from a thread executor.
    """
    gh = Github(auth=Auth.Token(token))
    rl = gh.get_rate_limit()
    return _format_rate_limit(rl)


def _format_rate_limit(rl) -> dict:
    """Shape a PyGithub RateLimitOverview object into a JSON-serialisable dict.

    PyGithub's ``get_rate_limit()`` returns a ``RateLimitOverview`` whose
    per-bucket fields (core/search/graphql) live on the nested ``resources``
    object, not on the overview itself. Older code assumed ``rl.core`` directly
    and blew up with ``AttributeError``; we walk through ``.resources`` now and
    fall back to the overview for forward/backward compatibility.
    """
    def bucket(resource) -> dict | None:
        if resource is None:
            return None
        limit = resource.limit or 0
        remaining = resource.remaining or 0
        return {
            "limit": limit,
            "remaining": remaining,
            "used": max(limit - remaining, 0),
            "resets_at": resource.reset.isoformat() if resource.reset else None,
        }

    resources = getattr(rl, "resources", rl)
    return {
        "core": bucket(getattr(resources, "core", None)),
        "search": bucket(getattr(resources, "search", None)),
        "graphql": bucket(getattr(resources, "graphql", None)),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
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
