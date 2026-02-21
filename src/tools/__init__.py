from __future__ import annotations
from src.tools import list_dir
from src.tools import list_working_tree
from src.tools import project_memory_delete_variable
from src.tools import project_memory_count_lines
from src.tools import project_memory_concat
from src.tools import project_memory_append_to_variable
from src.tools import project_memory_get_variable
from src.tools import project_memory_list_variables
from src.tools import project_memory_read_lines
from src.tools import project_memory_set_variable
from src.tools import session_memory_count_lines
from src.tools import session_memory_concat
from src.tools import session_memory_append_to_variable
from src.tools import session_memory_delete_variable
from src.tools import session_memory_get_variable
from src.tools import session_memory_list_variables
from src.tools import session_memory_read_lines
from src.tools import session_memory_set_variable
from src.tools import count_text_file_lines
from src.tools import read_text_file
from src.tools import todo_list
from src.tools import report_impossible
from src.tools import search_by_regex
from src.tools import pwd
from src.tools import basic_web_request
from src.tools import brave_web_search

ALL_TOOL_DEFINITIONS: list[dict] = [
    list_dir.DEFINITION,
    list_working_tree.DEFINITION,
    project_memory_set_variable.DEFINITION,
    project_memory_get_variable.DEFINITION,
    project_memory_list_variables.DEFINITION,
    project_memory_delete_variable.DEFINITION,
    project_memory_concat.DEFINITION,
    project_memory_append_to_variable.DEFINITION,
    project_memory_count_lines.DEFINITION,
    project_memory_read_lines.DEFINITION,
    session_memory_set_variable.DEFINITION,
    session_memory_get_variable.DEFINITION,
    session_memory_list_variables.DEFINITION,
    session_memory_delete_variable.DEFINITION,
    session_memory_concat.DEFINITION,
    session_memory_append_to_variable.DEFINITION,
    session_memory_count_lines.DEFINITION,
    session_memory_read_lines.DEFINITION,
    count_text_file_lines.DEFINITION,
    read_text_file.DEFINITION,
    todo_list.DEFINITION,
    report_impossible.DEFINITION,
    search_by_regex.DEFINITION,
    pwd.DEFINITION,
    basic_web_request.DEFINITION,
    brave_web_search.DEFINITION,
]

_TOOL_MAP: dict[str, object] = {
    "list_dir": list_dir,
    "list_working_tree": list_working_tree,
    "project_memory_set_variable": project_memory_set_variable,
    "project_memory_get_variable": project_memory_get_variable,
    "project_memory_list_variables": project_memory_list_variables,
    "project_memory_delete_variable": project_memory_delete_variable,
    "project_memory_concat": project_memory_concat,
    "project_memory_append_to_variable": project_memory_append_to_variable,
    "project_memory_count_lines": project_memory_count_lines,
    "project_memory_read_lines": project_memory_read_lines,
    "session_memory_set_variable": session_memory_set_variable,
    "session_memory_get_variable": session_memory_get_variable,
    "session_memory_list_variables": session_memory_list_variables,
    "session_memory_delete_variable": session_memory_delete_variable,
    "session_memory_concat": session_memory_concat,
    "session_memory_append_to_variable": session_memory_append_to_variable,
    "session_memory_count_lines": session_memory_count_lines,
    "session_memory_read_lines": session_memory_read_lines,
    "count_text_file_lines": count_text_file_lines,
    "read_text_file": read_text_file,
    "todo_list": todo_list,
    "report_impossible": report_impossible,
    "search_by_regex": search_by_regex,
    "pwd": pwd,
    "basic_web_request": basic_web_request,
    "brave_web_search": brave_web_search,
}

def check_needs_approval(name: str, args: dict) -> bool:
    """Return True if this tool call requires user approval before executing."""
    module = _TOOL_MAP.get(name)
    if module is None:
        return False
    fn = getattr(module, "needs_approval", None)
    if fn is None:
        return False
    return bool(fn(args))


def execute_tool(name: str, args: dict, session_data: dict | None = None) -> str:
    module = _TOOL_MAP.get(name)
    if module is None:
        return f"Unknown tool: {name!r}"
    if session_data is None:
        session_data = {}
    return module.execute(args, session_data)
