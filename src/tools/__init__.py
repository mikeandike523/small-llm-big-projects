from __future__ import annotations
from src.tools import basic_web_request
from src.tools import brave_web_search
from src.tools import change_pwd
from src.tools import create_dir
from src.tools import create_text_file
from src.tools import delete_file
from src.tools import get_pwd
from src.tools import list_dir
from src.tools import list_working_tree
from src.tools import read_text_file_to_session_memory
from src.tools import remove_dir
from src.tools import report_impossible
from src.tools import search_by_regex
from src.tools import session_memory_apply_patch
from src.tools import session_memory_append_to_variable
from src.tools import session_memory_check_eol
from src.tools import session_memory_check_indentation
from src.tools import session_memory_concat
from src.tools import session_memory_convert_indentation
from src.tools import session_memory_copy_rename
from src.tools import session_memory_count_lines
from src.tools import session_memory_delete_lines
from src.tools import session_memory_delete_variable
from src.tools import session_memory_get_variable
from src.tools import session_memory_insert_lines
from src.tools import session_memory_list_variables
from src.tools import session_memory_normalize_eol
from src.tools import session_memory_read_lines
from src.tools import session_memory_replace_lines
from src.tools import session_memory_search_by_regex
from src.tools import session_memory_set_variable
from src.tools import todo_list
from src.tools import write_text_file_from_session_memory

ALL_TOOL_DEFINITIONS: list[dict] = [
    basic_web_request.DEFINITION,
    brave_web_search.DEFINITION,
    change_pwd.DEFINITION,
    create_dir.DEFINITION,
    create_text_file.DEFINITION,
    delete_file.DEFINITION,
    get_pwd.DEFINITION,
    list_dir.DEFINITION,
    list_working_tree.DEFINITION,
    read_text_file_to_session_memory.DEFINITION,
    remove_dir.DEFINITION,
    report_impossible.DEFINITION,
    search_by_regex.DEFINITION,
    session_memory_apply_patch.DEFINITION,
    session_memory_append_to_variable.DEFINITION,
    session_memory_check_eol.DEFINITION,
    session_memory_check_indentation.DEFINITION,
    session_memory_concat.DEFINITION,
    session_memory_convert_indentation.DEFINITION,
    session_memory_copy_rename.DEFINITION,
    session_memory_count_lines.DEFINITION,
    session_memory_delete_lines.DEFINITION,
    session_memory_delete_variable.DEFINITION,
    session_memory_get_variable.DEFINITION,
    session_memory_insert_lines.DEFINITION,
    session_memory_list_variables.DEFINITION,
    session_memory_normalize_eol.DEFINITION,
    session_memory_read_lines.DEFINITION,
    session_memory_replace_lines.DEFINITION,
    session_memory_search_by_regex.DEFINITION,
    session_memory_set_variable.DEFINITION,
    todo_list.DEFINITION,
    write_text_file_from_session_memory.DEFINITION,
    
]

_TOOL_MAP: dict[str, object] = {
    "basic_web_request": basic_web_request,
    "brave_web_search": brave_web_search,
    "change_pwd": change_pwd,
    "create_dir": create_dir,
    "create_text_file": create_text_file,
    "delete_file": delete_file,
    "get_pwd": get_pwd,
    "list_dir": list_dir,
    "list_working_tree": list_working_tree,
    "read_text_file": read_text_file_to_session_memory,
    "remove_dir": remove_dir,
    "report_impossible": report_impossible,
    "search_by_regex": search_by_regex,
    "session_memory_apply_patch": session_memory_apply_patch,
    "session_memory_append_to_variable": session_memory_append_to_variable,
    "session_memory_check_eol": session_memory_check_eol,
    "session_memory_check_indentation": session_memory_check_indentation,
    "session_memory_concat": session_memory_concat,
    "session_memory_convert_indentation": session_memory_convert_indentation,
    "session_memory_copy_rename": session_memory_copy_rename,
    "session_memory_count_lines": session_memory_count_lines,
    "session_memory_delete_lines": session_memory_delete_lines,
    "session_memory_delete_variable": session_memory_delete_variable,
    "session_memory_get_variable": session_memory_get_variable,
    "session_memory_insert_lines": session_memory_insert_lines,
    "session_memory_list_variables": session_memory_list_variables,
    "session_memory_normalize_eol": session_memory_normalize_eol,
    "session_memory_read_lines": session_memory_read_lines,
    "session_memory_replace_lines": session_memory_replace_lines,
    "session_memory_search_by_regex": session_memory_search_by_regex,
    "session_memory_set_variable": session_memory_set_variable,
    "todo_list": todo_list,
    "write_text_file_from_session_memory": write_text_file_from_session_memory,
    "read_text_file_to_session_memory": read_text_file_to_session_memory
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
    try:
        return module.execute(args, session_data)
    except Exception as e:
        return f"""
Failed to execute tool {name}:
{e}
""".strip()
