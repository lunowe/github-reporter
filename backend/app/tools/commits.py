# app/tools/commits.py
"""
Tool: get_commits – list recent commits with optional filters.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("get_commits")
def create_get_commits_tool(github_service: GitHubService, **kwargs) -> FunctionTool:

    class GetCommitsSchema(BaseModel):
        since: Optional[str] = Field(
            default=None,
            description="Startdatum im ISO-Format, z.B. '2026-04-07'. Commits ab diesem Datum.",
        )
        until: Optional[str] = Field(
            default=None,
            description="Enddatum im ISO-Format. Commits bis zu diesem Datum.",
        )
        author: Optional[str] = Field(
            default=None,
            description="GitHub-Benutzername, um nach Autor zu filtern.",
        )
        branch: str = Field(
            default="main",
            description="Branch-Name, z.B. 'main' oder 'develop'.",
        )
        limit: int = Field(
            default=20,
            description="Maximale Anzahl zurückgegebener Commits (max. 50).",
        )

    def get_commits(
        since: Optional[str] = None,
        until: Optional[str] = None,
        author: Optional[str] = None,
        branch: str = "main",
        limit: int = 20,
    ) -> str:
        since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else None
        until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if until else None
        limit = min(limit, 50)

        commits = github_service.get_recent_commits(
            since=since_dt, until=until_dt, author=author, branch=branch, limit=limit,
        )

        if not commits:
            return "Keine Commits im angegebenen Zeitraum gefunden."

        return to_tool_output(commits)

    return FunctionTool.from_defaults(
        fn=get_commits,
        name="get_commits",
        description=(
            "Listet die letzten Commits eines Repos auf. "
            "Nutze dieses Tool, um zu sehen, was in einem bestimmten Zeitraum, "
            "von einem bestimmten Autor oder auf einem bestimmten Branch gemacht wurde."
        ),
        fn_schema=GetCommitsSchema,
    )
