from __future__ import annotations
from src.tools import list_working_tree
from src.tools import project_memory_set_variable

ALL_TOOL_DEFINITIONS: list[dict] = [
    list_working_tree.DEFINITION,
    project_memory_set_variable.DEFINITION
]

_TOOL_MAP: dict[str, object] = {
    "list_working_tree": list_working_tree,
    "project_memory_set_variable":project_memory_set_variable
}

def execute_tool(name: str, args: dict) -> str:
    module = _TOOL_MAP.get(name)
    if module is None:
        return f"Unknown tool: {name!r}"
    return module.execute(args)
