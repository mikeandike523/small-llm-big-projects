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
from src.tools import dom_analyzer
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
from src.tools import restore_file
from src.tools import scrape_web_page
from src.tools import snapshot_file
from src.tools import search_filesystem_by_regex
from src.tools import session_memory
from src.tools import summarize_memory_item
from src.tools import text_editor
from src.tools import todo_list
from src.tools import wikipedia
from src.tools import write_text_file
from src.utils.tool_calling.arguments import validate_tool_args

# ---------------------------------------------------------------------------
# Framework-injected parameters — reserved names no tool may declare itself
# ---------------------------------------------------------------------------

_RESERVED_TOOL_PARAMS: frozenset[str] = frozenset({"request_unredacted"})

_REQUEST_UNREDACTED_PARAM: dict = {
    "type": "boolean",
    "description": (
        "Request to bypass secret redactor. "
        "Use only if absolutely needed. Requires user permission."
    ),
}


def _inject_framework_params(module: object, definition: dict) -> dict:
    """Return a deep copy of definition with framework-managed parameters injected.

    Currently injects 'request_unredacted' for modules that opt in via
    ALLOW_REQUEST_UNREDACTED = True.
    """
    result = copy.deepcopy(definition)
    if getattr(module, "ALLOW_REQUEST_UNREDACTED", False):
        params = result.setdefault("function", {}).setdefault("parameters", {})
        params.setdefault("properties", {})["request_unredacted"] = _REQUEST_UNREDACTED_PARAM
        # Intentionally NOT added to "required" — it is optional, default false.
    return result


ALL_TOOL_DEFINITIONS: list[dict] = [
    _inject_framework_params(basic_web_request, basic_web_request.DEFINITION),
    _inject_framework_params(code_interpreter, code_interpreter.DEFINITION),
    _inject_framework_params(dom_analyzer, dom_analyzer.DEFINITION),
    _inject_framework_params(brave_web_search, brave_web_search.DEFINITION),
    _inject_framework_params(change_pwd, change_pwd.DEFINITION),
    _inject_framework_params(create_dir, create_dir.DEFINITION),
    _inject_framework_params(create_text_file, create_text_file.DEFINITION),
    _inject_framework_params(delete_file, delete_file.DEFINITION),
    _inject_framework_params(find_files_by_name, find_files_by_name.DEFINITION),
    _inject_framework_params(line_reader, line_reader.DEFINITION),
    _inject_framework_params(get_environment_info, get_environment_info.DEFINITION),
    _inject_framework_params(get_global_workspace_dir, get_global_workspace_dir.DEFINITION),
    _inject_framework_params(get_pwd, get_pwd.DEFINITION),
    _inject_framework_params(host_check_command, host_check_command.DEFINITION),
    _inject_framework_params(host_shell, host_shell.DEFINITION),
    _inject_framework_params(check_terminal_state, check_terminal_state.DEFINITION),
    _inject_framework_params(open_in_terminal, open_in_terminal.DEFINITION),
    _inject_framework_params(read_open_terminal, read_open_terminal.DEFINITION),
    _inject_framework_params(list_dir, list_dir.DEFINITION),
    _inject_framework_params(list_working_tree, list_working_tree.DEFINITION),
    _inject_framework_params(read_text_file, read_text_file.DEFINITION),
    _inject_framework_params(remove_dir, remove_dir.DEFINITION),
    _inject_framework_params(report_impossible, report_impossible.DEFINITION),
    _inject_framework_params(restore_file, restore_file.DEFINITION),
    _inject_framework_params(scrape_web_page, scrape_web_page.DEFINITION),
    _inject_framework_params(snapshot_file, snapshot_file.DEFINITION),
    _inject_framework_params(search_filesystem_by_regex, search_filesystem_by_regex.DEFINITION),
    _inject_framework_params(session_memory, session_memory.DEFINITION),
    _inject_framework_params(summarize_memory_item, summarize_memory_item.DEFINITION),
    _inject_framework_params(text_editor, text_editor.DEFINITION),
    _inject_framework_params(todo_list, todo_list.DEFINITION),
    _inject_framework_params(wikipedia, wikipedia.DEFINITION),
    _inject_framework_params(write_text_file, write_text_file.DEFINITION),
]

_TOOL_MAP: dict[str, object] = {
    "basic_web_request": basic_web_request,
    "code_interpreter": code_interpreter,
    "dom_analyzer": dom_analyzer,
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
    "restore_file": restore_file,
    "scrape_web_page": scrape_web_page,
    "snapshot_file": snapshot_file,
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


def validate_no_reserved_params(tool_map: dict) -> str | None:
    """Check that no tool in tool_map explicitly declares a reserved framework parameter.

    Returns an error string if a violation is found, None if all tools are clean.
    Checks module.DEFINITION (the raw, pre-injection definition) so injected params
    added by _inject_framework_params are never flagged as violations.
    """
    for tool_name, module in tool_map.items():
        props = (
            getattr(module, "DEFINITION", {})
            .get("function", {})
            .get("parameters", {})
            .get("properties", {})
            or {}
        )
        for reserved in _RESERVED_TOOL_PARAMS:
            if reserved in props:
                return (
                    f"Tool '{tool_name}' explicitly declares reserved parameter "
                    f"'{reserved}'. This parameter is managed by the framework and "
                    "must not be defined in tool source code."
                )
    return None


def check_needs_approval(
    name: str,
    args: dict,
    tool_map: dict | None = None,
    session_cwd: str | None = None,
    session_current_cwd: str | None = None,
    session_data: dict | None = None,
) -> bool:
    """Return True if this tool call requires user approval before executing.

    Short-circuits immediately to True when request_unredacted=True is present —
    the tool's own needs_approval is never consulted in that case. This is a hard
    gate: bypassing the redactor always requires explicit user permission, with no
    code path that can reach execution without it.
    """
    # Hard gate: request_unredacted=True forces approval unconditionally.
    # Do NOT call the tool's needs_approval — the answer is already True.
    if args.get("request_unredacted"):
        return True

    module = (tool_map if tool_map is not None else _TOOL_MAP).get(name)
    if module is None:
        return False
    fn = getattr(module, "needs_approval", None)
    if fn is None:
        return False
    from src.tools._approval import set_approval_cwd, set_approval_current_cwd

    clean_args = {k: v for k, v in args.items() if k not in _RESERVED_TOOL_PARAMS}
    set_approval_cwd(session_cwd or None)
    set_approval_current_cwd(session_current_cwd or None)
    try:
        if _accepts_session_data(fn):
            return bool(fn(clean_args, session_data))
        return bool(fn(clean_args))
    finally:
        set_approval_cwd(None)
        set_approval_current_cwd(None)


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

    # Determine bypass before stripping args: request_unredacted=True AND the tool
    # opted in. Both conditions must hold — if the tool did not opt in, bypass is
    # False and the result still goes through the redactor.
    bypass_redaction = bool(args.get("request_unredacted")) and bool(
        getattr(module, "ALLOW_REQUEST_UNREDACTED", False)
    )

    # Strip framework-managed params before validation and execution so tool code
    # never sees them and validate_tool_args doesn't reject them as extra properties.
    clean_args = {k: v for k, v in args.items() if k not in _RESERVED_TOOL_PARAMS}

    try:
        validate_tool_args(module.DEFINITION, clean_args)
        fn = module.execute
        if special_resources is not None and _accepts_special_resources(fn):
            result = fn(clean_args, session_data, special_resources)
        else:
            result = fn(clean_args, session_data)
    except (ToolHangError, ToolTimeoutError):
        raise
    except Exception as e:
        if os.environ.get("SLBP_TOOL_TRACEBACKS") == "1":
            tb = traceback.format_exc()
            result = f"Failed to execute tool {name}:\n{tb}".rstrip()
        else:
            result = f"Failed to execute tool {name}:\n{e}"

    if bypass_redaction:
        return result

    from src.redaction.core import redact as _redact
    _fp = args.get("path") or args.get("filepath") or None
    file_path = _fp if isinstance(_fp, str) else None
    return _redact(file_path, result)


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
) -> tuple[list[dict], dict, list[dict], dict]:
    """
    Load custom tool plugins from tools_dir.

    Returns (extra_definitions, extra_tool_map, plugin_info_list, custom_exclusions).
    extra_definitions and extra_tool_map contain only the newly loaded tools —
    callers merge them with the base ALL_TOOL_DEFINITIONS / _TOOL_MAP after applying
    custom_exclusions (same format as _exclude_builtin_tools.EXCLUDE).

    session_prefix is prepended to sys.modules keys to prevent collisions when
    multiple sessions load tools from the same path simultaneously.

    Raises RuntimeError on any loading error.
    """
    if workspace_root and workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

    extra_defs: list[dict] = []
    extra_map: dict = {}
    plugins: list[dict] = []

    # Execute tools-level __init__.py if present (e.g. to add site-packages to sys.path).
    tools_init = os.path.join(tools_dir, "__init__.py")
    if os.path.isfile(tools_init):
        tools_init_module_name = f"_slbp_{session_prefix}_tools_init"
        try:
            tools_init_spec = importlib.util.spec_from_file_location(
                tools_init_module_name, tools_init
            )
            tools_init_module = importlib.util.module_from_spec(tools_init_spec)
            sys.modules[tools_init_module_name] = tools_init_module
            tools_init_spec.loader.exec_module(tools_init_module)
        except Exception as e:
            sys.modules.pop(tools_init_module_name, None)
            raise RuntimeError(
                f"Failed to execute tools/__init__.py at {tools_init!r}: {e}"
            ) from e

    # Load optional _exclude_builtin_tools.py from the tools dir root.
    custom_exclusions: dict = {}
    exclude_file = os.path.join(tools_dir, "_exclude_builtin_tools.py")
    if os.path.isfile(exclude_file):
        excl_module_name = f"_slbp_{session_prefix}_exclude_builtin_tools"
        try:
            excl_spec = importlib.util.spec_from_file_location(excl_module_name, exclude_file)
            excl_module = importlib.util.module_from_spec(excl_spec)
            excl_spec.loader.exec_module(excl_module)
            loaded = getattr(excl_module, "EXCLUDE", {})
            if not isinstance(loaded, dict):
                raise RuntimeError(
                    f"_exclude_builtin_tools.py at {exclude_file!r} must define EXCLUDE as a dict."
                )
            custom_exclusions = loaded
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to load _exclude_builtin_tools.py at {exclude_file!r}: {e}"
            ) from e

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

            # Validate before injection: reserved params must not be declared by the tool.
            raw_props = (
                module.DEFINITION.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                or {}
            )
            for _reserved in _RESERVED_TOOL_PARAMS:
                if _reserved in raw_props:
                    sys.modules.pop(module_name, None)
                    raise RuntimeError(
                        f"Custom tool {tool_path!r} explicitly declares reserved parameter "
                        f"'{_reserved}'. This parameter is managed by the framework and "
                        "must not be defined in tool source code."
                    )

            # Inject framework params into a copy, then set the namespaced tool name.
            prefixed_def = _inject_framework_params(module, module.DEFINITION)
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

    return extra_defs, extra_map, plugins, custom_exclusions
