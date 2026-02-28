from __future__ import annotations
import copy
import importlib.util
import inspect
import os
import sys
import traceback
from src.tools import basic_web_request
from src.tools import code_interpreter
from src.tools import brave_web_search
from src.tools import change_pwd
from src.tools import create_dir
from src.tools import create_text_file
from src.tools import delete_file
from src.tools import get_pwd
from src.tools import list_dir
from src.tools import list_working_tree
from src.tools import load_skill_files_from_url_to_session_memory
from src.tools import project_memory_delete_variable
from src.tools import project_memory_get_variable
from src.tools import project_memory_list_variables
from src.tools import project_memory_search_by_regex
from src.tools import project_memory_set_variable
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
    code_interpreter.DEFINITION,
    brave_web_search.DEFINITION,
    change_pwd.DEFINITION,
    create_dir.DEFINITION,
    create_text_file.DEFINITION,
    delete_file.DEFINITION,
    get_pwd.DEFINITION,
    list_dir.DEFINITION,
    list_working_tree.DEFINITION,
    load_skill_files_from_url_to_session_memory.DEFINITION,
    project_memory_delete_variable.DEFINITION,
    project_memory_get_variable.DEFINITION,
    project_memory_list_variables.DEFINITION,
    project_memory_search_by_regex.DEFINITION,
    project_memory_set_variable.DEFINITION,
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
    "code_interpreter": code_interpreter,
    "brave_web_search": brave_web_search,
    "change_pwd": change_pwd,
    "create_dir": create_dir,
    "create_text_file": create_text_file,
    "delete_file": delete_file,
    "get_pwd": get_pwd,
    "list_dir": list_dir,
    "list_working_tree": list_working_tree,
    "load_skill_files_from_url_to_session_memory": load_skill_files_from_url_to_session_memory,
    "project_memory_delete_variable": project_memory_delete_variable,
    "project_memory_get_variable": project_memory_get_variable,
    "project_memory_list_variables": project_memory_list_variables,
    "project_memory_search_by_regex": project_memory_search_by_regex,
    "project_memory_set_variable": project_memory_set_variable,
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
    "read_text_file_to_session_memory": read_text_file_to_session_memory,
}

# ---------------------------------------------------------------------------
# Load exclusions (_exclude_builtin_tools.py)
# ---------------------------------------------------------------------------

try:
    from src.tools._exclude_builtin_tools import EXCLUDE as _load_exclusions
except ImportError:
    _load_exclusions = {}

_load_excluded: set[str] = {
    name for name, flags in _load_exclusions.items()
    if flags.get("loading") is True
}

if _load_excluded:
    ALL_TOOL_DEFINITIONS = [
        d for d in ALL_TOOL_DEFINITIONS
        if d.get("function", {}).get("name") not in _load_excluded
    ]
    for _excl_name in _load_excluded:
        _TOOL_MAP.pop(_excl_name, None)


def check_needs_approval(name: str, args: dict) -> bool:
    """Return True if this tool call requires user approval before executing."""
    module = _TOOL_MAP.get(name)
    if module is None:
        return False
    fn = getattr(module, "needs_approval", None)
    if fn is None:
        return False
    return bool(fn(args))


def _accepts_special_resources(fn) -> bool:
    """Return True if the tool's execute function declares a third parameter."""
    try:
        return len(inspect.signature(fn).parameters) >= 3
    except (ValueError, TypeError):
        return False


def execute_tool(
    name: str,
    args: dict,
    session_data: dict | None = None,
    special_resources: dict | None = None,
) -> str:
    module = _TOOL_MAP.get(name)
    if module is None:
        return f"Unknown tool: {name!r}"
    if session_data is None:
        session_data = {}
    try:
        validate_tool_args(module.DEFINITION, args)
        fn = module.execute
        if special_resources is not None and _accepts_special_resources(fn):
            return fn(args, session_data, special_resources)
        return fn(args, session_data)
    except Exception as e:
        if os.environ.get("SLBP_TOOL_TRACEBACKS") == "1":
            tb = traceback.format_exc()
            return f"Failed to execute tool {name}:\n{tb}".rstrip()
        return f"Failed to execute tool {name}:\n{e}"


# ---------------------------------------------------------------------------
# Custom tool plugins metadata (populated during loading below)
# ---------------------------------------------------------------------------

_custom_tool_plugins: list[dict] = []

# ---------------------------------------------------------------------------
# Custom tool loading — subfolder-per-plugin
# ---------------------------------------------------------------------------

if os.environ.get("SLBP_LOAD_CUSTOM_TOOLS") == "1":
    _custom_tools_root = os.path.join(os.getcwd(), "tools")

    # Insert cwd into sys.path so plugins can do:  from tools.moltbook.helpers import ...
    _workspace_root = os.getcwd()
    sys.path.insert(0, _workspace_root)

    # Enumerate plugin subdirectories
    try:
        _plugin_candidates = sorted(
            entry for entry in os.listdir(_custom_tools_root)
            if os.path.isdir(os.path.join(_custom_tools_root, entry))
        )
    except (FileNotFoundError, OSError) as _e:
        print(
            f"[slbp] ERROR: --load-custom-tools is set but cannot list tools/ directory"
            f" at {_custom_tools_root!r}: {_e}",
            file=sys.stderr,
        )
        sys.exit(1)

    for _plugin_name in _plugin_candidates:
        _plugin_dir = os.path.join(_custom_tools_root, _plugin_name)
        _plugin_init = os.path.join(_plugin_dir, "__init__.py")

        # Skip subdirs without __init__.py (not a plugin package)
        if not os.path.isfile(_plugin_init):
            continue

        # Load __init__.py to get TOOL_NAMESPACE
        _init_module_name = f"_custom_plugin_init_{_plugin_name}"
        try:
            _init_spec = importlib.util.spec_from_file_location(_init_module_name, _plugin_init)
            _init_module = importlib.util.module_from_spec(_init_spec)
            _init_spec.loader.exec_module(_init_module)
        except Exception as _e:
            print(
                f"[slbp] ERROR: Failed to import plugin __init__.py at {_plugin_init!r}: {_e}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not hasattr(_init_module, "TOOL_NAMESPACE"):
            print(
                f"[slbp] ERROR: Plugin __init__.py at {_plugin_init!r} is missing required"
                f" attribute 'TOOL_NAMESPACE'.",
                file=sys.stderr,
            )
            sys.exit(1)

        _tool_namespace: str = _init_module.TOOL_NAMESPACE

        # Enumerate tool files in this plugin directory
        try:
            _plugin_files = sorted(
                f for f in os.listdir(_plugin_dir)
                if f.lower().endswith(".py") and f != "__init__.py"
            )
        except (FileNotFoundError, OSError) as _e:
            print(
                f"[slbp] ERROR: Cannot list plugin directory {_plugin_dir!r}: {_e}",
                file=sys.stderr,
            )
            sys.exit(1)

        _plugin_tool_count = 0

        for _tool_file in _plugin_files:
            _tool_path = os.path.join(_plugin_dir, _tool_file)
            _stem = os.path.splitext(_tool_file)[0]
            _module_name = f"_custom_{_tool_namespace}_{_stem}"

            if _module_name in sys.modules:
                print(
                    f"[slbp] ERROR: Custom tool file {_tool_path!r} would be loaded"
                    f" as module {_module_name!r}, but that name is already in sys.modules."
                    f" Rename the file to resolve this collision.",
                    file=sys.stderr,
                )
                sys.exit(1)

            try:
                _spec = importlib.util.spec_from_file_location(_module_name, _tool_path)
                _module = importlib.util.module_from_spec(_spec)
                sys.modules[_module_name] = _module
                _spec.loader.exec_module(_module)
            except Exception as _e:
                sys.modules.pop(_module_name, None)
                print(
                    f"[slbp] ERROR: Failed to import custom tool {_tool_path!r}: {_e}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # No DEFINITION means it's a helper module — silently skip
            if not hasattr(_module, "DEFINITION"):
                sys.modules.pop(_module_name, None)
                continue

            if not hasattr(_module, "execute"):
                sys.modules.pop(_module_name, None)
                print(
                    f"[slbp] ERROR: Custom tool {_tool_path!r} has DEFINITION but is missing"
                    f" required function 'execute'.",
                    file=sys.stderr,
                )
                sys.exit(1)

            _base_tool_name = _module.DEFINITION.get("function", {}).get("name")
            if not _base_tool_name:
                sys.modules.pop(_module_name, None)
                print(
                    f"[slbp] ERROR: Custom tool {_tool_path!r} has a DEFINITION dict"
                    f" that is missing 'function.name'.",
                    file=sys.stderr,
                )
                sys.exit(1)

            _tool_name = f"{_tool_namespace}_{_base_tool_name}"

            if _tool_name in _TOOL_MAP:
                sys.modules.pop(_module_name, None)
                print(
                    f"[slbp] ERROR: Custom tool {_tool_name!r} (from {_tool_path!r})"
                    f" collides with an existing tool of the same name. Rename the tool to"
                    f" resolve this collision.",
                    file=sys.stderr,
                )
                sys.exit(1)

            _prefixed_def = copy.deepcopy(_module.DEFINITION)
            _prefixed_def["function"]["name"] = _tool_name
            ALL_TOOL_DEFINITIONS.append(_prefixed_def)
            _TOOL_MAP[_tool_name] = _module
            _plugin_tool_count += 1

        _custom_tool_plugins.append({
            "name": _plugin_name,
            "count": _plugin_tool_count,
            "path": _plugin_dir.replace("\\", "/"),
        })
