from __future__ import annotations
from src.tools import list_working_tree
from src.tools import project_memory_delete_variable
from src.tools import project_memory_get_variable
from src.tools import project_memory_list_variables
from src.tools import project_memory_set_variable
from src.tools import session_memory_delete_variable
from src.tools import session_memory_get_variable
from src.tools import session_memory_list_variables
from src.tools import session_memory_set_variable
from src.tools import read_text_file

ALL_TOOL_DEFINITIONS: list[dict] = [
    list_working_tree.DEFINITION,
    project_memory_set_variable.DEFINITION,
    project_memory_get_variable.DEFINITION,
    project_memory_list_variables.DEFINITION,
    project_memory_delete_variable.DEFINITION,
    session_memory_set_variable.DEFINITION,
    session_memory_get_variable.DEFINITION,
    session_memory_list_variables.DEFINITION,
    session_memory_delete_variable.DEFINITION,
    read_text_file.DEFINITION
]

_TOOL_MAP: dict[str, object] = {
    "list_working_tree": list_working_tree,
    "project_memory_set_variable": project_memory_set_variable,
    "project_memory_get_variable": project_memory_get_variable,
    "project_memory_list_variables": project_memory_list_variables,
    "project_memory_delete_variable": project_memory_delete_variable,
    "session_memory_set_variable": session_memory_set_variable,
    "session_memory_get_variable": session_memory_get_variable,
    "session_memory_list_variables": session_memory_list_variables,
    "session_memory_delete_variable": session_memory_delete_variable,
    "read_text_file":read_text_file
}

def execute_tool(name: str, args: dict, session_data: dict | None = None) -> str:
    module = _TOOL_MAP.get(name)
    if module is None:
        return f"Unknown tool: {name!r}"
    if session_data is None:
        session_data = {}
    return module.execute(args, session_data)
