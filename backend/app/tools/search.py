# app/tools/search.py
"""
Tool: search_code – search for code patterns across the repository.
"""

from typing import Optional

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("search_code")
def create_search_code_tool(github_service: GitHubService, **kwargs) -> FunctionTool:

    class SearchCodeSchema(BaseModel):
        query: str = Field(
            ...,
            description=(
                "Suchbegriff oder Code-Muster, z.B. 'useState', 'import axios', "
                "'def create_user', 'TODO'. Wird im gesamten Repository gesucht."
            ),
        )
        path: Optional[str] = Field(
            default=None,
            description=(
                "Suche auf einen Pfad einschränken, z.B. 'src/components' oder 'backend/app'. "
                "Leer = gesamtes Repository."
            ),
        )
        extension: Optional[str] = Field(
            default=None,
            description=(
                "Dateierweiterung filtern, z.B. 'py', 'ts', 'vue', 'json'. "
                "Ohne Punkt angeben."
            ),
        )
        limit: int = Field(
            default=15,
            description="Maximale Anzahl zurückgegebener Treffer (max. 30).",
        )

    def search_code(
        query: str,
        path: Optional[str] = None,
        extension: Optional[str] = None,
        limit: int = 15,
    ) -> str:
        limit = min(limit, 30)
        results = github_service.search_code(
            query=query, path=path, extension=extension, limit=limit,
        )

        if not results:
            return "Keine Treffer gefunden."
        if len(results) == 1 and "error" in results[0]:
            return f"Fehler: {results[0]['error']}"

        return to_tool_output(results)

    return FunctionTool.from_defaults(
        fn=search_code,
        name="search_code",
        description=(
            "Durchsucht den Code des Repositories nach einem Suchbegriff oder Muster. "
            "Gibt die Dateipfade und passende Code-Ausschnitte zurück. "
            "Nutze dieses Tool, um zu finden wo eine bestimmte Funktion, Variable, "
            "Import oder ein Muster im Code verwendet wird. "
            "Kann mit path und extension eingegrenzt werden."
        ),
        fn_schema=SearchCodeSchema,
    )
