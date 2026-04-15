# app/tools/pull_requests.py
"""
Tools: list_pull_requests + get_pr_detail
"""

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("pull_requests")
def create_pull_request_tools(github_service: GitHubService, **kwargs) -> list[FunctionTool]:

    # ── list_pull_requests ──────────────────────────────────────────────

    class ListPRsSchema(BaseModel):
        state: str = Field(
            default="open",
            description="Status-Filter: 'open', 'closed' oder 'all'.",
        )
        limit: int = Field(
            default=20,
            description="Maximale Anzahl zurückgegebener PRs (max. 50).",
        )

    def list_pull_requests(state: str = "open", limit: int = 20) -> str:
        limit = min(limit, 50)
        prs = github_service.get_pull_requests(state=state, limit=limit)
        if not prs:
            return f"Keine Pull Requests mit Status '{state}' gefunden."
        return to_tool_output(prs)

    list_prs_tool = FunctionTool.from_defaults(
        fn=list_pull_requests,
        name="list_pull_requests",
        description=(
            "Listet Pull Requests nach Status auf (open/closed/all). "
            "Nutze dieses Tool, um einen Überblick über offene oder kürzlich geschlossene PRs zu bekommen."
        ),
        fn_schema=ListPRsSchema,
    )

    # ── get_pr_detail ───────────────────────────────────────────────────

    class PRDetailSchema(BaseModel):
        pr_number: int = Field(
            description="Die Nummer des Pull Requests, z.B. 42.",
        )

    def get_pr_detail(pr_number: int) -> str:
        detail = github_service.get_pr_detail(pr_number)
        return to_tool_output(detail)

    pr_detail_tool = FunctionTool.from_defaults(
        fn=get_pr_detail,
        name="get_pr_detail",
        description=(
            "Holt detaillierte Informationen zu einem einzelnen Pull Request – "
            "einschließlich geänderter Dateien, Reviews, CI-Status und Merge-Status. "
            "Nutze dieses Tool, wenn nach einem bestimmten PR gefragt wird."
        ),
        fn_schema=PRDetailSchema,
    )

    return [list_prs_tool, pr_detail_tool]
