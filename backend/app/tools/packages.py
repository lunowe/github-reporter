# app/tools/packages.py
"""
GHCR / GitHub Container Registry tools.

Exposes four tools to the agent:
  - list_container_packages      – overview of images published on ghcr.io
  - get_container_image_tags     – tags/versions of one image
  - get_container_image_details  – detail view (optionally for one tag)
  - find_image_for_commit        – which image/tag was produced by a commit

All four require the token to have the 'read:packages' scope (classic PAT)
or equivalent fine-grained permission. For private images the token also
needs access to the publishing repo.
"""

from typing import Optional

from pydantic import BaseModel, Field
from llama_index.core.tools import FunctionTool

from app.tools.registry import register_tool
from app.services.github_service import GitHubService
from app.utils import to_tool_output


# ── 1. List all container images ─────────────────────────────────────────

@register_tool("list_container_packages")
def create_list_container_packages_tool(
    github_service: GitHubService, **kwargs,
) -> FunctionTool:

    class ListPackagesSchema(BaseModel):
        only_this_repo: bool = Field(
            default=True,
            description=(
                "Wenn True (Standard): nur Container-Images, die laut GitHub "
                "mit diesem Repo verknüpft sind. False = alle Images der "
                "Org bzw. des Users."
            ),
        )

    def list_container_packages(only_this_repo: bool = True) -> str:
        pkgs = github_service.list_container_packages(only_this_repo=only_this_repo)
        if not pkgs:
            return (
                "Keine Container-Images auf GHCR gefunden. "
                "Mögliche Ursachen: das Repo publiziert keine Images, "
                "das Token hat den Scope 'read:packages' nicht, oder die Images "
                "sind privat und für dieses Token nicht sichtbar."
            )
        return to_tool_output(pkgs)

    return FunctionTool.from_defaults(
        fn=list_container_packages,
        name="list_container_packages",
        description=(
            "Listet Container-Images (Docker/OCI) auf, die auf GitHub Container "
            "Registry (ghcr.io) für den Owner dieses Repositories veröffentlicht "
            "sind. Liefert pro Image: Name, Sichtbarkeit (public/private), Anzahl "
            "der Versionen, verknüpftes Repo und ghcr.io-Referenz. "
            "Einstiegs-Tool, um zu sehen, welche Images überhaupt existieren."
        ),
        fn_schema=ListPackagesSchema,
    )


# ── 2. Tags/versions of one image ────────────────────────────────────────

@register_tool("get_container_image_tags")
def create_get_container_image_tags_tool(
    github_service: GitHubService, **kwargs,
) -> FunctionTool:

    class ImageTagsSchema(BaseModel):
        package_name: str = Field(
            description=(
                "Name des Container-Images ohne Registry- und Owner-Prefix, "
                "z.B. 'myapp' oder 'backend/api'."
            ),
        )
        limit: int = Field(
            default=30,
            description="Maximale Anzahl Versionen (max. 100).",
        )

    def get_container_image_tags(package_name: str, limit: int = 30) -> str:
        versions = github_service.get_container_image_tags(package_name, limit=limit)
        if not versions:
            return (
                f"Keine Versionen/Tags für Image '{package_name}' gefunden. "
                "Bitte Image-Name und Berechtigungen (read:packages) prüfen."
            )
        return to_tool_output(versions)

    return FunctionTool.from_defaults(
        fn=get_container_image_tags,
        name="get_container_image_tags",
        description=(
            "Listet alle Versionen eines Container-Images auf GHCR. Eine Version "
            "entspricht einem Push (identifiziert durch SHA256-Digest) und trägt "
            "0..N Tags (z.B. 'latest', 'v1.2.3', 'main-abc1234'). Nutze dieses "
            "Tool, um zu sehen, welche Tags verfügbar sind, welcher Tag am "
            "aktuellsten ist und ob untaggte Altversionen existieren."
        ),
        fn_schema=ImageTagsSchema,
    )


# ── 3. Detail view ───────────────────────────────────────────────────────

@register_tool("get_container_image_details")
def create_get_container_image_details_tool(
    github_service: GitHubService, **kwargs,
) -> FunctionTool:

    class ImageDetailsSchema(BaseModel):
        package_name: str = Field(
            description="Name des Container-Images, z.B. 'myapp'.",
        )
        tag: Optional[str] = Field(
            default=None,
            description=(
                "Optional ein spezifischer Tag (z.B. 'latest' oder 'v1.0.0'). "
                "Leer = Zusammenfassung über alle Versionen."
            ),
        )

    def get_container_image_details(
        package_name: str,
        tag: Optional[str] = None,
    ) -> str:
        details = github_service.get_container_image_details(package_name, tag=tag)
        return to_tool_output(details)

    return FunctionTool.from_defaults(
        fn=get_container_image_details,
        name="get_container_image_details",
        description=(
            "Detailinformationen zu einem Container-Image auf GHCR: Sichtbarkeit "
            "(public/private), verknüpftes Repo, Gesamtzahl Versionen. "
            "Mit 'tag': Digest und Zeitstempel dieser konkreten Version. "
            "Ohne 'tag': Überblick inkl. neuester Version und Tag-Auswahl. "
            "Nutze dieses Tool, wenn der User nach Details zu einem bestimmten "
            "Image oder Tag fragt (z.B. 'wann wurde :latest gepusht?')."
        ),
        fn_schema=ImageDetailsSchema,
    )


# ── 4. Commit → image cross-reference ────────────────────────────────────

@register_tool("find_image_for_commit")
def create_find_image_for_commit_tool(
    github_service: GitHubService, **kwargs,
) -> FunctionTool:

    class FindImageSchema(BaseModel):
        commit_sha: str = Field(
            description="Commit-SHA, vollständig oder mindestens 7 Zeichen.",
        )
        package_name: Optional[str] = Field(
            default=None,
            description=(
                "Optional auf ein bestimmtes Image einschränken. Leer = alle "
                "mit dem Repo verknüpften Images durchsuchen."
            ),
        )

    def find_image_for_commit(
        commit_sha: str,
        package_name: Optional[str] = None,
    ) -> str:
        result = github_service.find_image_for_commit(
            commit_sha, package_name=package_name,
        )
        return to_tool_output(result)

    return FunctionTool.from_defaults(
        fn=find_image_for_commit,
        name="find_image_for_commit",
        description=(
            "Findet Container-Images/Tags, die zu einem bestimmten Commit gehören "
            "– erkennt typische CI-Muster wie 'sha-abc1234', 'main-abc1234' oder "
            "den bloßen Short-SHA (docker/metadata-action-Stil). Liefert als "
            "Kontext zusätzlich die Check-Runs dieses Commits, sodass klar wird, "
            "ob der zugehörige Build-Job erfolgreich lief. Nutze dieses Tool, "
            "wenn der User wissen will, ob bzw. als welches Image ein Commit "
            "oder PR publiziert wurde."
        ),
        fn_schema=FindImageSchema,
    )
