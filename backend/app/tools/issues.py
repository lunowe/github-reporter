# app/tools/issues.py
"""
Tools: list_issues + get_issue_detail
"""

from typing import Optional

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("issues")
def create_issue_tools(github_service: GitHubService, **kwargs) -> list[FunctionTool]:

    # ── list_issues ─────────────────────────────────────────────────────

    class ListIssuesSchema(BaseModel):
        state: str = Field(
            default="open",
            description="Status-Filter: 'open', 'closed' oder 'all'.",
        )
        labels: Optional[str] = Field(
            default=None,
            description="Komma-getrennte Labels zum Filtern, z.B. 'bug,high-priority'.",
        )
        assignee: Optional[str] = Field(
            default=None,
            description="GitHub-Benutzername des Zugewiesenen.",
        )
        limit: int = Field(
            default=20,
            description="Maximale Anzahl (max. 50).",
        )

    def list_issues(
        state: str = "open",
        labels: Optional[str] = None,
        assignee: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        limit = min(limit, 50)
        label_list = [l.strip() for l in labels.split(",")] if labels else None
        issues = github_service.get_issues(
            state=state, labels=label_list, assignee=assignee, limit=limit,
        )
        if not issues:
            return f"Keine Issues mit Status '{state}' gefunden."
        return to_tool_output(issues)

    list_issues_tool = FunctionTool.from_defaults(
        fn=list_issues,
        name="list_issues",
        description=(
            "Listet Issues nach Status, Labels oder Zuweisungen auf. "
            "Nutze dieses Tool, um offene Bugs, Feature-Requests oder zugewiesene Aufgaben zu finden."
        ),
        fn_schema=ListIssuesSchema,
    )

    # ── get_issue_detail ────────────────────────────────────────────────

    class IssueDetailSchema(BaseModel):
        issue_number: int = Field(
            description="Die Nummer des Issues, z.B. 15.",
        )

    def get_issue_detail(issue_number: int) -> str:
        detail = github_service.get_issue_detail(issue_number)
        return to_tool_output(detail)

    issue_detail_tool = FunctionTool.from_defaults(
        fn=get_issue_detail,
        name="get_issue_detail",
        description=(
            "Holt detaillierte Informationen zu einem einzelnen Issue – "
            "einschließlich Beschreibung, Kommentare, Labels und Milestone. "
            "Nutze dieses Tool für Details zu einem bestimmten Issue."
        ),
        fn_schema=IssueDetailSchema,
    )

    return [list_issues_tool, issue_detail_tool]
