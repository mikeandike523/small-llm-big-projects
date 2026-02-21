from __future__ import annotations
from src.tools import apply_patch
from src.tools import create_dir
from src.tools import create_text_file
from src.tools import delete_file
from src.tools import file_check_eol
from src.tools import file_check_indentation
from src.tools import file_convert_indentation
from src.tools import file_normalize_eol
from src.tools import list_dir
from src.tools import list_working_tree
from src.tools import project_memory_check_eol
from src.tools import project_memory_check_indentation
from src.tools import project_memory_convert_indentation
from src.tools import project_memory_copy_rename
from src.tools import project_memory_delete_variable
from src.tools import project_memory_count_lines
from src.tools import project_memory_concat
from src.tools import project_memory_append_to_variable
from src.tools import project_memory_get_variable
from src.tools import project_memory_list_variables
from src.tools import project_memory_normalize_eol
from src.tools import project_memory_read_lines
from src.tools import project_memory_set_variable
from src.tools import remove_dir
from src.tools import session_memory_check_eol
from src.tools import session_memory_check_indentation
from src.tools import session_memory_convert_indentation
from src.tools import session_memory_copy_rename
from src.tools import session_memory_count_lines
from src.tools import session_memory_concat
from src.tools import session_memory_append_to_variable
from src.tools import session_memory_delete_variable
from src.tools import session_memory_get_variable
from src.tools import session_memory_list_variables
from src.tools import session_memory_normalize_eol
from src.tools import session_memory_read_lines
from src.tools import session_memory_set_variable
from src.tools import transfer_memory
from src.tools import count_text_file_lines
from src.tools import read_text_file
from src.tools import todo_list
from src.tools import report_impossible
from src.tools import search_by_regex
from src.tools import pwd
from src.tools import basic_web_request
from src.tools import brave_web_search

ALL_TOOL_DEFINITIONS: list[dict] = [
    apply_patch.DEFINITION,
    create_dir.DEFINITION,
    create_text_file.DEFINITION,
    delete_file.DEFINITION,
    file_check_eol.DEFINITION,
    file_check_indentation.DEFINITION,
    file_convert_indentation.DEFINITION,
    file_normalize_eol.DEFINITION,
    list_dir.DEFINITION,
    list_working_tree.DEFINITION,
    project_memory_check_eol.DEFINITION,
    project_memory_check_indentation.DEFINITION,
    project_memory_convert_indentation.DEFINITION,
    project_memory_copy_rename.DEFINITION,
    project_memory_set_variable.DEFINITION,
    project_memory_get_variable.DEFINITION,
    project_memory_list_variables.DEFINITION,
    project_memory_delete_variable.DEFINITION,
    project_memory_concat.DEFINITION,
    project_memory_append_to_variable.DEFINITION,
    project_memory_count_lines.DEFINITION,
    project_memory_normalize_eol.DEFINITION,
    project_memory_read_lines.DEFINITION,
    remove_dir.DEFINITION,
    session_memory_check_eol.DEFINITION,
    session_memory_check_indentation.DEFINITION,
    session_memory_convert_indentation.DEFINITION,
    session_memory_copy_rename.DEFINITION,
    session_memory_set_variable.DEFINITION,
    session_memory_get_variable.DEFINITION,
    session_memory_list_variables.DEFINITION,
    session_memory_delete_variable.DEFINITION,
    session_memory_concat.DEFINITION,
    session_memory_append_to_variable.DEFINITION,
    session_memory_count_lines.DEFINITION,
    session_memory_normalize_eol.DEFINITION,
    session_memory_read_lines.DEFINITION,
    transfer_memory.DEFINITION,
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
    "apply_patch": apply_patch,
    "create_dir": create_dir,
    "create_text_file": create_text_file,
    "delete_file": delete_file,
    "file_check_eol": file_check_eol,
    "file_check_indentation": file_check_indentation,
    "file_convert_indentation": file_convert_indentation,
    "file_normalize_eol": file_normalize_eol,
    "list_dir": list_dir,
    "list_working_tree": list_working_tree,
    "project_memory_check_eol": project_memory_check_eol,
    "project_memory_check_indentation": project_memory_check_indentation,
    "project_memory_convert_indentation": project_memory_convert_indentation,
    "project_memory_copy_rename": project_memory_copy_rename,
    "project_memory_set_variable": project_memory_set_variable,
    "project_memory_get_variable": project_memory_get_variable,
    "project_memory_list_variables": project_memory_list_variables,
    "project_memory_delete_variable": project_memory_delete_variable,
    "project_memory_concat": project_memory_concat,
    "project_memory_append_to_variable": project_memory_append_to_variable,
    "project_memory_count_lines": project_memory_count_lines,
    "project_memory_normalize_eol": project_memory_normalize_eol,
    "project_memory_read_lines": project_memory_read_lines,
    "remove_dir": remove_dir,
    "session_memory_check_eol": session_memory_check_eol,
    "session_memory_check_indentation": session_memory_check_indentation,
    "session_memory_convert_indentation": session_memory_convert_indentation,
    "session_memory_copy_rename": session_memory_copy_rename,
    "session_memory_set_variable": session_memory_set_variable,
    "session_memory_get_variable": session_memory_get_variable,
    "session_memory_list_variables": session_memory_list_variables,
    "session_memory_delete_variable": session_memory_delete_variable,
    "session_memory_concat": session_memory_concat,
    "session_memory_append_to_variable": session_memory_append_to_variable,
    "session_memory_count_lines": session_memory_count_lines,
    "session_memory_normalize_eol": session_memory_normalize_eol,
    "session_memory_read_lines": session_memory_read_lines,
    "transfer_memory": transfer_memory,
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
