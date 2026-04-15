# app/tools/compare.py
"""
Tool: compare_branches – diff between two branches or commits.
"""

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("compare_branches")
def create_compare_branches_tool(github_service: GitHubService, **kwargs) -> FunctionTool:

    class CompareBranchesSchema(BaseModel):
        base: str = Field(
            ...,
            description=(
                "Basis-Branch oder Commit-SHA, z.B. 'main', 'v1.0.0', oder 'abc1234'. "
                "Der Ausgangspunkt des Vergleichs."
            ),
        )
        head: str = Field(
            ...,
            description=(
                "Ziel-Branch oder Commit-SHA, z.B. 'develop', 'feature/auth'. "
                "Wird mit der Basis verglichen."
            ),
        )

    def compare_branches(base: str, head: str) -> str:
        result = github_service.compare_branches(base=base, head=head)
        if "error" in result:
            return f"Fehler: {result['error']}"
        return to_tool_output(result)

    return FunctionTool.from_defaults(
        fn=compare_branches,
        name="compare_branches",
        description=(
            "Vergleicht zwei Branches oder Commits und zeigt den Unterschied: "
            "Anzahl Commits, geänderte Dateien, Additions/Deletions. "
            "Nutze dieses Tool, um zu sehen, was sich zwischen zwei Branches geändert hat, "
            "z.B. 'Was ist in develop aber noch nicht in main?'."
        ),
        fn_schema=CompareBranchesSchema,
    )
