from __future__ import annotations
from src.tools import list_working_tree

ALL_TOOL_DEFINITIONS: list[dict] = [
    list_working_tree.DEFINITION,
]

_TOOL_MAP: dict[str, object] = {
    "list-working-tree": list_working_tree,
}

def execute_tool(name: str, args: dict) -> str:
    module = _TOOL_MAP.get(name)
    if module is None:
        return f"Unknown tool: {name!r}"
    return module.execute(args)
