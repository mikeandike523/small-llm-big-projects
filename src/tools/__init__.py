from __future__ import annotations
import copy
import importlib.util
import inspect
import os
import sys
import traceback
from src.utils.exceptions import ToolHangError, ToolTimeoutError
from src.tools import basic_web_request
from src.tools import code_interpreter
from src.tools import brave_web_search
from src.tools import change_pwd
from src.tools import create_dir
from src.tools import create_text_file
from src.tools import delete_file
from src.tools import find_files_by_name
from src.tools import line_reader
from src.tools import get_environment_info
from src.tools import get_global_workspace_dir
from src.tools import get_pwd
from src.tools import host_check_command
from src.tools import host_shell
from src.tools import check_terminal_state
from src.tools import open_in_terminal
from src.tools import read_open_terminal
from src.tools import list_dir
from src.tools import list_working_tree
from src.tools import read_text_file
from src.tools import remove_dir
from src.tools import report_impossible
from src.tools import scrape_web_page
from src.tools import search_filesystem_by_regex
from src.tools import session_memory
from src.tools import summarize_memory_item
from src.tools import text_editor
from src.tools import todo_list
from src.tools import wikipedia
from src.tools import write_text_file
from src.utils.tool_calling.arguments import validate_tool_args

ALL_TOOL_DEFINITIONS: list[dict] = [
    basic_web_request.DEFINITION,
    code_interpreter.DEFINITION,
    brave_web_search.DEFINITION,
    change_pwd.DEFINITION,
    create_dir.DEFINITION,
    create_text_file.DEFINITION,
    delete_file.DEFINITION,
    find_files_by_name.DEFINITION,
    line_reader.DEFINITION,
    get_environment_info.DEFINITION,
    get_global_workspace_dir.DEFINITION,
    get_pwd.DEFINITION,
    host_check_command.DEFINITION,
    host_shell.DEFINITION,
    check_terminal_state.DEFINITION,
    open_in_terminal.DEFINITION,
    read_open_terminal.DEFINITION,
    list_dir.DEFINITION,
    list_working_tree.DEFINITION,
    read_text_file.DEFINITION,
    remove_dir.DEFINITION,
    report_impossible.DEFINITION,
    scrape_web_page.DEFINITION,
    search_filesystem_by_regex.DEFINITION,
    session_memory.DEFINITION,
    summarize_memory_item.DEFINITION,
    text_editor.DEFINITION,
    todo_list.DEFINITION,
    wikipedia.DEFINITION,
    write_text_file.DEFINITION,
]

_TOOL_MAP: dict[str, object] = {
    "basic_web_request": basic_web_request,
    "code_interpreter": code_interpreter,
    "brave_web_search": brave_web_search,
    "change_pwd": change_pwd,
    "create_dir": create_dir,
    "create_text_file": create_text_file,
    "delete_file": delete_file,
    "find_files_by_name": find_files_by_name,
    "line_reader": line_reader,
    "get_environment_info": get_environment_info,
    "get_global_workspace_dir": get_global_workspace_dir,
    "get_pwd": get_pwd,
    "host_check_command": host_check_command,
    "host_shell": host_shell,
    "check_terminal_state": check_terminal_state,
    "open_in_terminal": open_in_terminal,
    "read_open_terminal": read_open_terminal,
    "list_dir": list_dir,
    "list_working_tree": list_working_tree,
    "read_text_file": read_text_file,
    "remove_dir": remove_dir,
    "report_impossible": report_impossible,
    "scrape_web_page": scrape_web_page,
    "search_filesystem_by_regex": search_filesystem_by_regex,
    "session_memory": session_memory,
    "summarize_memory_item": summarize_memory_item,
    "text_editor": text_editor,
    "todo_list": todo_list,
    "wikipedia": wikipedia,
    "write_text_file": write_text_file,
}

# ---------------------------------------------------------------------------
# Load exclusions (_exclude_builtin_tools.py)
# ---------------------------------------------------------------------------

try:
    from src.tools._exclude_builtin_tools import EXCLUDE as _load_exclusions
except ImportError:
    _load_exclusions = {}

_load_excluded: set[str] = {
    name for name, flags in _load_exclusions.items() if flags.get("loading") is True
}

if _load_excluded:
    ALL_TOOL_DEFINITIONS = [
        d
        for d in ALL_TOOL_DEFINITIONS
        if d.get("function", {}).get("name") not in _load_excluded
    ]
    for _excl_name in _load_excluded:
        _TOOL_MAP.pop(_excl_name, None)


def check_needs_approval(
    name: str, args: dict, tool_map: dict | None = None, session_cwd: str | None = None
) -> bool:
    """Return True if this tool call requires user approval before executing."""
    module = (tool_map if tool_map is not None else _TOOL_MAP).get(name)
    if module is None:
        return False
    fn = getattr(module, "needs_approval", None)
    if fn is None:
        return False
    from src.tools._approval import set_approval_cwd

    set_approval_cwd(session_cwd or None)
    try:
        return bool(fn(args))
    finally:
        set_approval_cwd(None)


def _accepts_session_data(fn) -> bool:
    """Return True if the function declares a second parameter (session_data)."""
    try:
        return len(inspect.signature(fn).parameters) >= 2
    except (ValueError, TypeError):
        return False


def get_dirty_effects(
    name: str,
    args: dict,
    session_data: dict | None = None,
    tool_map: dict | None = None,
) -> dict:
    """Return the dirty effects dict for a tool call, or {} if the tool defines none."""
    module = (tool_map if tool_map is not None else _TOOL_MAP).get(name)
    if module is None:
        return {}
    fn = getattr(module, "dirty_effects", None)
    if fn is None:
        return {}
    try:
        if session_data is not None and _accepts_session_data(fn):
            return fn(args, session_data) or {}
        return fn(args) or {}
    except Exception:
        return {}


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
    tool_map: dict | None = None,
) -> str:
    actual_map = tool_map if tool_map is not None else _TOOL_MAP
    module = actual_map.get(name)
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
    except (ToolHangError, ToolTimeoutError):
        raise
    except Exception as e:
        if os.environ.get("SLBP_TOOL_TRACEBACKS") == "1":
            tb = traceback.format_exc()
            return f"Failed to execute tool {name}:\n{tb}".rstrip()
        return f"Failed to execute tool {name}:\n{e}"


# ---------------------------------------------------------------------------
# Custom tool plugins metadata (empty at server start; populated per-session)
# ---------------------------------------------------------------------------

_custom_tool_plugins: list[dict] = []

# ---------------------------------------------------------------------------
# Custom tool loading — called at session-creation time, not server start
# ---------------------------------------------------------------------------


def load_custom_tools(
    tools_dir: str,
    workspace_root: str | None = None,
    session_prefix: str = "",
) -> tuple[list[dict], dict, list[dict]]:
    """
    Load custom tool plugins from tools_dir.

    Returns (extra_definitions, extra_tool_map, plugin_info_list).
    extra_definitions and extra_tool_map contain only the newly loaded tools —
    callers merge them with the base ALL_TOOL_DEFINITIONS / _TOOL_MAP.

    session_prefix is prepended to sys.modules keys to prevent collisions when
    multiple sessions load tools from the same path simultaneously.

    Raises RuntimeError on any loading error.
    """
    if workspace_root and workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

    extra_defs: list[dict] = []
    extra_map: dict = {}
    plugins: list[dict] = []

    try:
        plugin_candidates = sorted(
            entry
            for entry in os.listdir(tools_dir)
            if os.path.isdir(os.path.join(tools_dir, entry))
        )
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f"Cannot list tools/ directory at {tools_dir!r}: {e}") from e

    for plugin_name in plugin_candidates:
        plugin_dir = os.path.join(tools_dir, plugin_name)
        plugin_init = os.path.join(plugin_dir, "__init__.py")

        if not os.path.isfile(plugin_init):
            continue

        init_module_name = f"_slbp_{session_prefix}_plugin_init_{plugin_name}"
        try:
            init_spec = importlib.util.spec_from_file_location(
                init_module_name, plugin_init
            )
            init_module = importlib.util.module_from_spec(init_spec)
            init_spec.loader.exec_module(init_module)
        except Exception as e:
            raise RuntimeError(
                f"Failed to import plugin __init__.py at {plugin_init!r}: {e}"
            ) from e

        if not hasattr(init_module, "TOOL_NAMESPACE"):
            raise RuntimeError(
                f"Plugin __init__.py at {plugin_init!r} is missing required attribute 'TOOL_NAMESPACE'."
            )

        tool_namespace: str = init_module.TOOL_NAMESPACE

        try:
            plugin_files = sorted(
                f
                for f in os.listdir(plugin_dir)
                if f.lower().endswith(".py") and f != "__init__.py"
            )
        except (FileNotFoundError, OSError) as e:
            raise RuntimeError(
                f"Cannot list plugin directory {plugin_dir!r}: {e}"
            ) from e

        plugin_tool_count = 0

        for tool_file in plugin_files:
            tool_path = os.path.join(plugin_dir, tool_file)
            stem = os.path.splitext(tool_file)[0]
            module_name = f"_slbp_{session_prefix}_{tool_namespace}_{stem}"

            if module_name in sys.modules:
                raise RuntimeError(
                    f"Custom tool file {tool_path!r} would be loaded as module {module_name!r},"
                    f" but that name is already in sys.modules. Rename the file to resolve this collision."
                )

            try:
                spec = importlib.util.spec_from_file_location(module_name, tool_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                sys.modules.pop(module_name, None)
                raise RuntimeError(
                    f"Failed to import custom tool {tool_path!r}: {e}"
                ) from e

            if not hasattr(module, "DEFINITION"):
                sys.modules.pop(module_name, None)
                continue

            if not hasattr(module, "execute"):
                sys.modules.pop(module_name, None)
                raise RuntimeError(
                    f"Custom tool {tool_path!r} has DEFINITION but is missing required function 'execute'."
                )

            base_tool_name = module.DEFINITION.get("function", {}).get("name")
            if not base_tool_name:
                sys.modules.pop(module_name, None)
                raise RuntimeError(
                    f"Custom tool {tool_path!r} has a DEFINITION dict that is missing 'function.name'."
                )

            tool_name = f"{tool_namespace}_{base_tool_name}"

            if tool_name in _TOOL_MAP or tool_name in extra_map:
                sys.modules.pop(module_name, None)
                raise RuntimeError(
                    f"Custom tool {tool_name!r} (from {tool_path!r}) collides with an existing tool."
                    f" Rename the tool to resolve this collision."
                )

            prefixed_def = copy.deepcopy(module.DEFINITION)
            prefixed_def["function"]["name"] = tool_name
            extra_defs.append(prefixed_def)
            extra_map[tool_name] = module
            plugin_tool_count += 1

        plugins.append(
            {
                "name": plugin_name,
                "count": plugin_tool_count,
                "path": plugin_dir.replace("\\", "/"),
            }
        )

    return extra_defs, extra_map, plugins
