# app/tools/registry.py
"""
Tool registry – adapted from chatforen's agent_tools_factory.py.
@register_tool decorator + build_all_tools assembler.
"""

from typing import Callable

from llama_index.core.tools import FunctionTool

from app.services.github_service import GitHubService

TOOL_REGISTRY: dict[str, Callable] = {}


def register_tool(tool_id: str):
    """Decorator to register a tool factory."""
    def decorator(fn: Callable) -> Callable:
        TOOL_REGISTRY[tool_id] = fn
        return fn
    return decorator


def build_all_tools(github_service: GitHubService) -> list[FunctionTool]:
    """Instantiate every registered tool for the given GitHubService."""
    # Ensure all tool modules are imported so decorators run
    import app.tools.commits          # noqa: F401
    import app.tools.pull_requests    # noqa: F401
    import app.tools.issues           # noqa: F401
    import app.tools.actions          # noqa: F401
    import app.tools.repo_summary     # noqa: F401
    import app.tools.browse           # noqa: F401
    import app.tools.compare          # noqa: F401
    import app.tools.contributors     # noqa: F401
    import app.tools.search           # noqa: F401

    tools: list[FunctionTool] = []
    for tool_id, factory in TOOL_REGISTRY.items():
        result = factory(github_service=github_service)
        if isinstance(result, list):
            tools.extend(result)
        else:
            tools.append(result)
    return tools
