from __future__ import annotations
import copy
import importlib.util
import os
import sys
from src.tools import basic_web_request
from src.tools import brave_web_search
from src.tools import change_pwd
from src.tools import create_dir
from src.tools import create_text_file
from src.tools import delete_file
from src.tools import get_pwd
from src.tools import list_dir
from src.tools import list_working_tree
from src.tools import load_skill_files_from_url_to_session_memory
from src.tools import read_text_file_to_session_memory
from src.tools import remove_dir
from src.tools import report_impossible
from src.tools import search_filesystem_by_regex
from src.tools import session_memory_apply_patch
from src.tools import session_memory_append_to_variable
from src.tools import session_memory_check_eol
from src.tools import session_memory_check_indentation
from src.tools import session_memory_concat
from src.tools import session_memory_convert_indentation
from src.tools import session_memory_copy_rename
from src.tools import session_memory_count_chars
from src.tools import session_memory_count_lines
from src.tools import session_memory_delete_lines
from src.tools import session_memory_delete_variable
from src.tools import session_memory_get_variable
from src.tools import session_memory_insert_lines
from src.tools import session_memory_list_variables
from src.tools import session_memory_normalize_eol
from src.tools import session_memory_read_char_range
from src.tools import session_memory_read_lines
from src.tools import session_memory_replace_lines
from src.tools import session_memory_search_by_regex
from src.tools import session_memory_set_variable
from src.tools import todo_list
from src.tools import write_text_file_from_session_memory
from src.utils.tool_calling.arguments import validate_tool_args

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
    load_skill_files_from_url_to_session_memory.DEFINITION,
    read_text_file_to_session_memory.DEFINITION,
    remove_dir.DEFINITION,
    report_impossible.DEFINITION,
    search_filesystem_by_regex.DEFINITION,
    session_memory_apply_patch.DEFINITION,
    session_memory_append_to_variable.DEFINITION,
    session_memory_check_eol.DEFINITION,
    session_memory_check_indentation.DEFINITION,
    session_memory_concat.DEFINITION,
    session_memory_convert_indentation.DEFINITION,
    session_memory_copy_rename.DEFINITION,
    session_memory_count_chars.DEFINITION,
    session_memory_count_lines.DEFINITION,
    session_memory_delete_lines.DEFINITION,
    session_memory_delete_variable.DEFINITION,
    session_memory_get_variable.DEFINITION,
    session_memory_insert_lines.DEFINITION,
    session_memory_list_variables.DEFINITION,
    session_memory_normalize_eol.DEFINITION,
    session_memory_read_char_range.DEFINITION,
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
    "load_skill_files_from_url_to_session_memory": load_skill_files_from_url_to_session_memory,
    "read_text_file": read_text_file_to_session_memory,
    "remove_dir": remove_dir,
    "report_impossible": report_impossible,
    "search_filesystem_by_regex": search_filesystem_by_regex,
    "session_memory_apply_patch": session_memory_apply_patch,
    "session_memory_append_to_variable": session_memory_append_to_variable,
    "session_memory_check_eol": session_memory_check_eol,
    "session_memory_check_indentation": session_memory_check_indentation,
    "session_memory_concat": session_memory_concat,
    "session_memory_convert_indentation": session_memory_convert_indentation,
    "session_memory_copy_rename": session_memory_copy_rename,
    "session_memory_count_chars": session_memory_count_chars,
    "session_memory_count_lines": session_memory_count_lines,
    "session_memory_delete_lines": session_memory_delete_lines,
    "session_memory_delete_variable": session_memory_delete_variable,
    "session_memory_get_variable": session_memory_get_variable,
    "session_memory_insert_lines": session_memory_insert_lines,
    "session_memory_list_variables": session_memory_list_variables,
    "session_memory_normalize_eol": session_memory_normalize_eol,
    "session_memory_read_char_range": session_memory_read_char_range,
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
        validate_tool_args(module.DEFINITION,args)
        return module.execute(args, session_data)
    except Exception as e:
        return f"""
Failed to execute tool {name}:
{e}
""".strip()


if os.environ.get("SLBP_LOAD_CUSTOM_TOOLS") == "1":
    _custom_tools_dir = os.path.join(os.getcwd(), "tools")

    # --- load __init__.py to get TOOL_NAMESPACE ---
    _init_path = os.path.join(_custom_tools_dir, "__init__.py")
    if not os.path.isfile(_init_path):
        print(
            f"[slbp] ERROR: --load-custom-tools is set but tools/__init__.py not found"
            f" at {_init_path!r}. Create it and define TOOL_NAMESPACE.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _init_spec = importlib.util.spec_from_file_location("_custom_tools_init", _init_path)
        _init_module = importlib.util.module_from_spec(_init_spec)
        _init_spec.loader.exec_module(_init_module)
    except Exception as _e:
        print(
            f"[slbp] ERROR: Failed to import tools/__init__.py at {_init_path!r}: {_e}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not hasattr(_init_module, "TOOL_NAMESPACE"):
        print(
            f"[slbp] ERROR: tools/__init__.py at {_init_path!r} is missing required"
            f" attribute 'TOOL_NAMESPACE'.",
            file=sys.stderr,
        )
        sys.exit(1)

    _tool_namespace: str = _init_module.TOOL_NAMESPACE

    # --- add workspace root to sys.path so tools can import tools.helpers etc. ---
    _workspace_root = os.path.dirname(_custom_tools_dir)
    sys.path.insert(0, _workspace_root)

    # --- enumerate tool files, skipping __init__.py ---
    try:
        _custom_tool_files = sorted(
            f for f in os.listdir(_custom_tools_dir)
            if f.lower().endswith(".py") and f != "__init__.py"
        )
    except (FileNotFoundError, OSError) as _e:
        print(
            f"[slbp] ERROR: --load-custom-tools is set but cannot list tools/ directory"
            f" at {_custom_tools_dir!r}: {_e}",
            file=sys.stderr,
        )
        sys.exit(1)

    for _custom_tool_file in _custom_tool_files:
        _custom_tool_path = os.path.join(_custom_tools_dir, _custom_tool_file)
        _module_name = f"{_tool_namespace}_{os.path.splitext(_custom_tool_file)[0]}"

        if _module_name in sys.modules:
            print(
                f"[slbp] ERROR: Custom tool file {_custom_tool_path!r} would be loaded"
                f" as module {_module_name!r}, but that name is already in sys.modules."
                f" Rename the file to resolve this collision.",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            _spec = importlib.util.spec_from_file_location(_module_name, _custom_tool_path)
            _module = importlib.util.module_from_spec(_spec)
            sys.modules[_module_name] = _module
            _spec.loader.exec_module(_module)
        except Exception as _e:
            sys.modules.pop(_module_name, None)
            print(
                f"[slbp] ERROR: Failed to import custom tool {_custom_tool_path!r}: {_e}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not hasattr(_module, "DEFINITION"):
            sys.modules.pop(_module_name, None)
            print(
                f"[slbp] ERROR: Custom tool {_custom_tool_path!r} is missing required"
                f" module-level attribute 'DEFINITION'.",
                file=sys.stderr,
            )
            sys.exit(1)

        if not hasattr(_module, "execute"):
            sys.modules.pop(_module_name, None)
            print(
                f"[slbp] ERROR: Custom tool {_custom_tool_path!r} is missing required"
                f" function 'execute'.",
                file=sys.stderr,
            )
            sys.exit(1)

        _base_tool_name = _module.DEFINITION.get("function", {}).get("name")
        if not _base_tool_name:
            sys.modules.pop(_module_name, None)
            print(
                f"[slbp] ERROR: Custom tool {_custom_tool_path!r} has a DEFINITION dict"
                f" that is missing 'function.name'.",
                file=sys.stderr,
            )
            sys.exit(1)

        _tool_name = f"{_tool_namespace}_{_base_tool_name}"

        if _tool_name in _TOOL_MAP:
            sys.modules.pop(_module_name, None)
            print(
                f"[slbp] ERROR: Custom tool {_tool_name!r} (from {_custom_tool_path!r})"
                f" collides with an existing tool of the same name. Rename the tool to"
                f" resolve this collision.",
                file=sys.stderr,
            )
            sys.exit(1)

        _prefixed_def = copy.deepcopy(_module.DEFINITION)
        _prefixed_def["function"]["name"] = _tool_name
        ALL_TOOL_DEFINITIONS.append(_prefixed_def)
        _TOOL_MAP[_tool_name] = _module
