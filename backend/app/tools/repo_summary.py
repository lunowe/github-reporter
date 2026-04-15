# app/tools/repo_summary.py
"""
Tool: get_repo_summary – high-level repository overview.
"""

from pydantic import BaseModel
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("get_repo_summary")
def create_repo_summary_tool(github_service: GitHubService, **kwargs) -> FunctionTool:

    class RepoSummarySchema(BaseModel):
        pass  # No parameters – aggregates everything

    def get_repo_summary() -> str:
        summary = github_service.get_repo_summary()
        return to_tool_output(summary)

    return FunctionTool.from_defaults(
        fn=get_repo_summary,
        name="get_repo_summary",
        description=(
            "Gibt eine Gesamtübersicht des Repositories zurück: "
            "Anzahl offener PRs und Issues, Branches, letzter Commit, CI-Status und mehr. "
            "Nutze dieses Tool als Einstieg, um den aktuellen Projektstatus zu verstehen."
        ),
        fn_schema=RepoSummarySchema,
    )
