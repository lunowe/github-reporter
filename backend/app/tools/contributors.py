# app/tools/contributors.py
"""
Tool: get_contributors – list contributors ranked by commit count.
"""

from pydantic import BaseModel, Field

from app.tools.registry import GitHubTool, register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("get_contributors")
def create_get_contributors_tool(github_service: GitHubService, **kwargs) -> GitHubTool:

    class GetContributorsSchema(BaseModel):
        limit: int = Field(
            default=20,
            description="Maximale Anzahl zurückgegebener Contributors (max. 50).",
        )

    def get_contributors(limit: int = 20) -> str:
        limit = min(limit, 50)
        result = github_service.get_contributors(limit=limit)
        if not result:
            return "Keine Contributors gefunden."
        return to_tool_output(result)

    return GitHubTool(
        fn=get_contributors,
        name="get_contributors",
        description=(
            "Listet die Contributors des Repositories sortiert nach Anzahl der Commits. "
            "Nutze dieses Tool, um zu sehen, wer am meisten beigetragen hat, "
            "wer aktiv ist, oder um einen Überblick über das Team zu bekommen."
        ),
        schema=GetContributorsSchema,
    )
