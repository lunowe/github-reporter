# app/tools/browse.py
"""
Tools: browse_directory + read_file – navigate and read repository code.
"""

from typing import Optional

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


@register_tool("browse_directory")
def create_browse_directory_tool(github_service: GitHubService, **kwargs) -> FunctionTool:

    class BrowseDirectorySchema(BaseModel):
        path: str = Field(
            default="",
            description=(
                "Pfad im Repository, z.B. '' (Root), 'src', 'src/components'. "
                "Leer = Wurzelverzeichnis."
            ),
        )
        ref: Optional[str] = Field(
            default=None,
            description="Branch oder Commit-SHA. Standard = Default-Branch.",
        )

    def browse_directory(path: str = "", ref: Optional[str] = None) -> str:
        result = github_service.browse_directory(path=path, ref=ref)
        if not result:
            return "Verzeichnis ist leer oder existiert nicht."
        return to_tool_output(result)

    return FunctionTool.from_defaults(
        fn=browse_directory,
        name="browse_directory",
        description=(
            "Listet Dateien und Ordner in einem Verzeichnis des Repositories auf. "
            "Nutze dieses Tool, um die Projektstruktur zu erkunden. "
            "Beginne mit path='' für das Wurzelverzeichnis und navigiere dann tiefer."
        ),
        fn_schema=BrowseDirectorySchema,
    )


@register_tool("read_file")
def create_read_file_tool(github_service: GitHubService, **kwargs) -> FunctionTool:

    class ReadFileSchema(BaseModel):
        path: str = Field(
            ...,
            description="Dateipfad im Repository, z.B. 'src/main.py' oder 'README.md'.",
        )
        ref: Optional[str] = Field(
            default=None,
            description="Branch oder Commit-SHA. Standard = Default-Branch.",
        )
        start_line: int = Field(
            default=1,
            description="Erste Zeile, die gelesen werden soll (ab 1).",
        )
        end_line: int = Field(
            default=300,
            description="Letzte Zeile, die gelesen werden soll (max. 500).",
        )

    def read_file(
        path: str,
        ref: Optional[str] = None,
        start_line: int = 1,
        end_line: int = 300,
    ) -> str:
        # Clamp to max 500 lines per request
        end_line = min(end_line, start_line + 499)
        result = github_service.read_file(
            path=path, ref=ref, start_line=start_line, end_line=end_line,
        )
        if "error" in result:
            return f"Fehler: {result['error']}"
        return to_tool_output(result)

    return FunctionTool.from_defaults(
        fn=read_file,
        name="read_file",
        description=(
            "Liest den Inhalt einer Datei im Repository mit Zeilennummern. "
            "Nutze dieses Tool, um Code, Konfigurationsdateien oder Dokumentation zu lesen. "
            "Bei großen Dateien kannst du einen Zeilenbereich angeben (z.B. start_line=100, end_line=200). "
            "Maximal 500 Zeilen pro Anfrage."
        ),
        fn_schema=ReadFileSchema,
    )
