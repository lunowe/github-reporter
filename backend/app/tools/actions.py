# app/tools/actions.py
"""
Tool: get_workflow_runs – CI/CD status from GitHub Actions.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.tools.registry import GitHubTool, register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("get_workflow_runs")
def create_workflow_runs_tool(github_service: GitHubService, **kwargs) -> GitHubTool:

    class WorkflowRunsSchema(BaseModel):
        status: Optional[str] = Field(
            default=None,
            description="Status-Filter: 'completed', 'in_progress', 'queued', 'failure', 'success'. Leer = alle.",
        )
        limit: int = Field(
            default=10,
            description="Maximale Anzahl zurückgegebener Runs (max. 30).",
        )

    def get_workflow_runs(status: Optional[str] = None, limit: int = 10) -> str:
        limit = min(limit, 30)
        runs = github_service.get_workflow_runs(status=status, limit=limit)
        if not runs:
            return "Keine Workflow-Runs gefunden."
        return to_tool_output(runs)

    return GitHubTool(
        fn=get_workflow_runs,
        name="get_workflow_runs",
        description=(
            "Listet GitHub Actions Workflow-Runs auf (CI/CD-Pipelines). "
            "Nutze dieses Tool, um den CI-Status zu prüfen – ob Builds laufen, bestanden oder fehlgeschlagen sind."
        ),
        schema=WorkflowRunsSchema,
    )
