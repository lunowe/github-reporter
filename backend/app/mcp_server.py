# app/mcp_server.py
"""
MCP server — exposes the GitHub Reporter tools over Streamable HTTP.

Mounted into the FastAPI app at `/mcp` (see app/main.py). Each request is
authenticated by a personal API key sent as `Authorization: Bearer ghr_...`
(or `X-API-Key: ghr_...`). The key resolves to its owning user, and every tool
call runs with that user's GitHub token and is restricted to repos the user may
access — exactly like the chat route.

Tools are thin wrappers around the existing tool registry: each wrapper takes a
`repo` argument plus the same parameters as the corresponding tool in
`app/tools/`, then dispatches through `build_all_tools()` so the data-fetching
and formatting logic stays in one place.

Issue write tools (create/update/comment) execute directly — MCP clients ask
the user to approve each tool call themselves. They're limited to
GitHub-authenticated accounts; read-only viewer keys get a clear refusal.
"""

from __future__ import annotations

import logging
import json
from typing import Literal, Optional

import anyio
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from github import GithubException

from app.services.api_key_service import authenticate_api_key
from app.services.github_service import GitHubService
from app.services.issue_actions import can_write, read_only_reason
from app.services.issue_writes import (
    IssueWriteError,
    build_comment,
    build_create,
    build_update,
    describe_github_error,
    execute,
)
from app.services.repo_access import get_authorized_repo
from app.services.token_resolver import resolve_github_token
from app.tools.registry import build_all_tools

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
GitHub Projekt-Reporter — Werkzeuge, um den Stand eines GitHub-Repositories \
abzufragen (Commits, Pull Requests, Issues, CI/CD, Code, Branch-Vergleiche, \
Container-Images) und um Issues anzulegen, zu bearbeiten und zu kommentieren. \
Jedes Tool erwartet einen `repo`-Parameter im Format 'owner/repo'. Zugriff ist \
auf die Repositories beschränkt, für die der API-Schlüssel berechtigt ist.\
"""

mcp = FastMCP("GitHub Reporter", instructions=INSTRUCTIONS)


# ── Auth & dispatch helpers ──────────────────────────────────────────────

def _extract_api_key() -> Optional[str]:
    """Pull the API key from the Authorization (Bearer) or X-API-Key header."""
    headers = get_http_headers(include={"authorization", "x-api-key"})
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return headers.get("x-api-key", "").strip() or None


async def _authenticated_user() -> tuple[dict, dict]:
    """Resolve the request's API key to (user, key document)."""
    key = _extract_api_key()
    if not key:
        raise ToolError(
            "Kein API-Schlüssel übergeben. Sende ihn als 'Authorization: Bearer ghr_...'."
        )
    auth = await authenticate_api_key(key)
    if not auth:
        raise ToolError("Ungültiger oder widerrufener API-Schlüssel.")
    return auth


async def _run(tool_name: str, repo: str, **params) -> str:
    """
    Authenticate, authorize the repo, then execute a registered tool.

    The GitHub work is synchronous (PyGithub), so it runs in a worker thread to
    avoid blocking the event loop.
    """
    user, _ = await _authenticated_user()

    repo_doc = await get_authorized_repo(user, repo)
    if not repo_doc:
        raise ToolError(
            f"Kein Zugriff auf '{repo}'. Prüfe den Namen (owner/repo) und deine Berechtigungen."
        )

    token = await resolve_github_token(user)

    def _work() -> str:
        service = GitHubService(token=token, repo_full_name=repo)
        for tool in build_all_tools(service):
            if tool.name == tool_name:
                return str(tool.fn(**params))
        raise ToolError(f"Unbekanntes Tool: {tool_name}")

    try:
        return await anyio.to_thread.run_sync(_work)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface a readable message, not a stack trace
        logger.exception("MCP tool %s failed for repo %s", tool_name, repo)
        raise ToolError(f"Fehler beim Abrufen der GitHub-Daten: {exc}") from exc


async def _run_write(repo: str, build, kind: str, issue_number: Optional[int] = None, **params) -> str:
    """Authenticate, check write permission + repo access, validate, then write."""
    user, key_doc = await _authenticated_user()
    if not can_write(user):
        if read_only_reason(user) == "suspended":
            raise ToolError("Dein Konto ist gesperrt – Issues bearbeiten ist nicht erlaubt.")
        raise ToolError("Dein Konto hat nur Lesezugriff – Issues bearbeiten ist nicht erlaubt.")
    if not key_doc.get("can_write"):
        raise ToolError(
            "Dieser API-Schlüssel hat keinen Schreibzugriff. Erstelle unter Einstellungen → "
            "API & MCP einen Schlüssel mit „Schreibzugriff“."
        )
    if not await get_authorized_repo(user, repo):
        raise ToolError(
            f"Kein Zugriff auf '{repo}'. Prüfe den Namen (owner/repo) und deine Berechtigungen."
        )
    token = await resolve_github_token(user)

    def _work() -> dict:
        service = GitHubService(token=token, repo_full_name=repo)
        if issue_number is not None:
            params["issue_number"] = issue_number
        built = build(service, **params)
        proposed = built[0] if isinstance(built, tuple) else built
        # No snapshot: the caller validated against the issue just now.
        return execute(service, kind=kind, proposed=proposed, issue_number=issue_number)

    try:
        result = await anyio.to_thread.run_sync(_work)
    except IssueWriteError as exc:
        raise ToolError(str(exc)) from exc
    except GithubException as exc:
        raise ToolError(describe_github_error(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("MCP write %s failed for repo %s", kind, repo)
        raise ToolError(f"Fehler beim Schreiben auf GitHub: {exc}") from exc
    logger.info("MCP write %s on %s → %s", kind, repo, result.get("html_url"))
    return json.dumps(result, ensure_ascii=False)


# ── Tools (mirror app/tools/*; logic lives in the registry) ───────────────

@mcp.tool
async def get_repo_summary(repo: str) -> str:
    """Gesamtübersicht des Repositories: offene PRs/Issues, Branches, letzter Commit, CI-Status."""
    return await _run("get_repo_summary", repo)


@mcp.tool
async def get_commits(
    repo: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    author: Optional[str] = None,
    branch: str = "main",
    limit: int = 20,
) -> str:
    """Listet die letzten Commits auf, optional gefiltert nach Datum (ISO), Autor oder Branch (max. 50)."""
    return await _run(
        "get_commits", repo,
        since=since, until=until, author=author, branch=branch, limit=limit,
    )


@mcp.tool
async def list_pull_requests(repo: str, state: str = "open", limit: int = 20) -> str:
    """Listet Pull Requests nach Status auf ('open', 'closed' oder 'all'; max. 50)."""
    return await _run("list_pull_requests", repo, state=state, limit=limit)


@mcp.tool
async def get_pr_detail(repo: str, pr_number: int) -> str:
    """Details zu einem Pull Request: geänderte Dateien, Reviews, CI- und Merge-Status."""
    return await _run("get_pr_detail", repo, pr_number=pr_number)


@mcp.tool
async def list_issues(
    repo: str,
    state: str = "open",
    labels: Optional[str] = None,
    assignee: Optional[str] = None,
    limit: int = 20,
) -> str:
    """Listet Issues nach Status, Labels (komma-getrennt) oder Zuweisung auf (max. 50)."""
    return await _run(
        "list_issues", repo,
        state=state, labels=labels, assignee=assignee, limit=limit,
    )


@mcp.tool
async def get_issue_detail(repo: str, issue_number: int) -> str:
    """Details zu einem Issue: Beschreibung, Kommentare, Labels und Milestone."""
    return await _run("get_issue_detail", repo, issue_number=issue_number)


@mcp.tool
async def get_workflow_runs(repo: str, status: Optional[str] = None, limit: int = 10) -> str:
    """Listet GitHub Actions Workflow-Runs (CI/CD-Status) auf, optional nach Status gefiltert (max. 30)."""
    return await _run("get_workflow_runs", repo, status=status, limit=limit)


@mcp.tool
async def browse_directory(repo: str, path: str = "", ref: Optional[str] = None) -> str:
    """Listet Dateien und Ordner eines Verzeichnisses auf (path='' = Wurzelverzeichnis)."""
    return await _run("browse_directory", repo, path=path, ref=ref)


@mcp.tool
async def read_file(
    repo: str,
    path: str,
    ref: Optional[str] = None,
    start_line: int = 1,
    end_line: int = 300,
) -> str:
    """Liest den Inhalt einer Datei mit Zeilennummern (optionaler Zeilenbereich, max. 500 Zeilen)."""
    return await _run(
        "read_file", repo,
        path=path, ref=ref, start_line=start_line, end_line=end_line,
    )


@mcp.tool
async def compare_branches(repo: str, base: str, head: str) -> str:
    """Vergleicht zwei Branches/Commits: Anzahl Commits, geänderte Dateien, Additions/Deletions."""
    return await _run("compare_branches", repo, base=base, head=head)


@mcp.tool
async def get_contributors(repo: str, limit: int = 20) -> str:
    """Listet Contributors sortiert nach Anzahl der Commits (max. 50)."""
    return await _run("get_contributors", repo, limit=limit)


@mcp.tool
async def search_code(
    repo: str,
    query: str,
    path: Optional[str] = None,
    extension: Optional[str] = None,
    limit: int = 15,
) -> str:
    """Durchsucht den Code des Repositories nach einem Begriff/Muster (optional auf path/extension eingrenzbar; max. 30)."""
    return await _run(
        "search_code", repo,
        query=query, path=path, extension=extension, limit=limit,
    )


@mcp.tool
async def list_container_packages(repo: str, only_this_repo: bool = True) -> str:
    """Listet Container-Images (ghcr.io) des Repo-Owners auf (benötigt Token-Scope 'read:packages')."""
    return await _run("list_container_packages", repo, only_this_repo=only_this_repo)


@mcp.tool
async def get_container_image_tags(repo: str, package_name: str, limit: int = 30) -> str:
    """Listet alle Versionen/Tags eines Container-Images auf GHCR auf (max. 100)."""
    return await _run("get_container_image_tags", repo, package_name=package_name, limit=limit)


@mcp.tool
async def get_container_image_details(repo: str, package_name: str, tag: Optional[str] = None) -> str:
    """Detailinformationen zu einem Container-Image (optional zu einem bestimmten Tag)."""
    return await _run("get_container_image_details", repo, package_name=package_name, tag=tag)


@mcp.tool
async def find_image_for_commit(repo: str, commit_sha: str, package_name: Optional[str] = None) -> str:
    """Findet Container-Images/Tags, die zu einem bestimmten Commit gehören (inkl. Check-Runs)."""
    return await _run("find_image_for_commit", repo, commit_sha=commit_sha, package_name=package_name)


# ── Issue write tools ────────────────────────────────────────────────────

@mcp.tool
async def create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: Optional[list[str]] = None,
    assignees: Optional[list[str]] = None,
) -> str:
    """Legt ein neues Issue an (nur existierende Labels; Body in Markdown). Gibt Nummer und URL zurück."""
    return await _run_write(
        repo, build_create, "create_issue",
        title=title, body=body, labels=labels, assignees=assignees,
    )


@mcp.tool
async def update_issue(
    repo: str,
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
    """Bearbeitet ein Issue; nur angegebene Felder ändern sich. `body` ersetzt die Beschreibung, `append_to_body` hängt an. Schließen mit state='closed'."""
    return await _run_write(
        repo, build_update, "update_issue", issue_number=issue_number,
        title=title, body=body, append_to_body=append_to_body,
        add_labels=add_labels, remove_labels=remove_labels,
        add_assignees=add_assignees, remove_assignees=remove_assignees,
        state=state, state_reason=state_reason,
    )


@mcp.tool
async def add_issue_comment(repo: str, issue_number: int, body: str) -> str:
    """Schreibt einen Kommentar (Markdown) zu einem Issue."""
    return await _run_write(repo, build_comment, "comment", issue_number=issue_number, body=body)


def create_mcp_app():
    """
    Build the Streamable HTTP ASGI app to mount into FastAPI (path-relative '/').

    `stateless_http` + `json_response` keep each call self-contained and make the
    endpoint trivially proxyable (plain JSON, no long-lived SSE) — which is what
    lets it sit behind the Nuxt `/mcp` proxy on the same public domain as the app.
    """
    return mcp.http_app(
        path="/",
        transport="streamable-http",
        stateless_http=True,
        json_response=True,
    )
