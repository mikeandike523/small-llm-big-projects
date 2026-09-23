from __future__ import annotations
import copy
import hashlib
import importlib.util
import inspect
import os
import sys
import threading
import traceback
from dataclasses import dataclass, field
from src.utils.exceptions import ToolHangError, ToolTimeoutError
from src.tools import basic_web_request
from src.tools import code_interpreter
from src.tools import dom_analyzer
from src.tools import brave_web_search
from src.tools import change_pwd
from src.tools import create_dir
from src.tools import create_text_file
from src.tools import copy_dir
from src.tools import copy_file
from src.tools import move_dir_or_file
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
from src.tools.config import TOOL_OUTPUT_MAX_COLUMNS
from src.utils.text_truncation import truncate_long_lines


def _truncate_columns(text: str) -> str:
    """Cap every line of a tool result at TOOL_OUTPUT_MAX_COLUMNS characters.

    Applied to every tool result in execute_tool so no single line of output
    (e.g. minified/compiled content) can flood the context window. See
    src/tools/config.py for the rationale and the no-escape-hatch policy.
    """
    if not isinstance(text, str):
        return text
    return truncate_long_lines(text, TOOL_OUTPUT_MAX_COLUMNS)


# ---------------------------------------------------------------------------
# Safe sibling-file imports for custom tool authors
# ---------------------------------------------------------------------------

_import_local_lock = threading.RLock()  # reentrant: an imported file's own top-level
# code may itself call import_local for a further sibling, from the same thread


def import_local(path: str) -> object:
    """Import a local Python file by path, safe to use from custom tool code.

    `path` may be absolute, or relative to the caller's own file (resolved
    against the caller's __file__ via the call stack) — so from a tool file,
    `import_local("_helpers.py")` imports the sibling file in the same
    directory.

    Unlike a bare `import _helpers` statement, this never depends on the
    filename being globally unique. sys.modules is one flat, process-wide
    namespace shared by every session and every plugin, so two different
    files that happen to share a name (a very plausible collision — this
    project's own docs use "_helpers.py" as the example) would otherwise
    silently resolve to whichever one was imported first, for the rest of
    the process's life, in every other session. The module name generated
    here is instead derived from the resolved absolute path, so two
    different files never collide, and repeated calls for the SAME path —
    by the same or a different session — return the same cached module,
    same semantics as a normal top-level `import`, just collision-safe.

    Because the cache is path-keyed (not session-keyed), a helper module
    imported this way is shared process-wide, like any other Python module —
    don't rely on this for a helper with mutable module-level state that
    must stay isolated per session.

    Raises ImportError/OSError if the file doesn't exist or fails to import
    (the underlying exception propagates; import errors are not swallowed).
    """
    if not os.path.isabs(path):
        caller_file = inspect.stack()[1].filename
        path = os.path.join(os.path.dirname(os.path.abspath(caller_file)), path)
    path = os.path.normcase(os.path.normpath(os.path.abspath(path)))

    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
    module_name = f"_slbp_local_{digest}"

    with _import_local_lock:
        cached = sys.modules.get(module_name)
        if cached is not None:
            return cached

        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot import local file: {path!r}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module


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

    Injects 'request_unredacted' only for modules that both opt into redaction
    (ENABLE_REDACTION = True) and don't explicitly forbid the bypass
    (ALLOW_REQUEST_UNREDACTED = False, default True). A tool with redaction
    disabled has nothing to bypass, so the parameter never appears for it. A
    tool that sets ALLOW_REQUEST_UNREDACTED = False is redacted with no bypass
    capability at all — the agent has no way to even ask, not merely a denial
    at approval time.
    """
    result = copy.deepcopy(definition)
    enable_redaction = getattr(module, "ENABLE_REDACTION", False)
    allow_unredacted = getattr(module, "ALLOW_REQUEST_UNREDACTED", True)
    if enable_redaction and allow_unredacted:
        params = result.setdefault("function", {}).setdefault("parameters", {})
        params.setdefault("properties", {})[
            "request_unredacted"
        ] = _REQUEST_UNREDACTED_PARAM
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
    _inject_framework_params(copy_dir, copy_dir.DEFINITION),
    _inject_framework_params(copy_file, copy_file.DEFINITION),
    _inject_framework_params(move_dir_or_file, move_dir_or_file.DEFINITION),
    _inject_framework_params(delete_file, delete_file.DEFINITION),
    _inject_framework_params(find_files_by_name, find_files_by_name.DEFINITION),
    _inject_framework_params(line_reader, line_reader.DEFINITION),
    _inject_framework_params(get_environment_info, get_environment_info.DEFINITION),
    _inject_framework_params(
        get_global_workspace_dir, get_global_workspace_dir.DEFINITION
    ),
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
    _inject_framework_params(
        search_filesystem_by_regex, search_filesystem_by_regex.DEFINITION
    ),
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
    "copy_dir": copy_dir,
    "copy_file": copy_file,
    "move_dir_or_file": move_dir_or_file,
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
    session_data: dict | None = None,
    special_resources: dict | None = None,
) -> bool:
    """Return True if this tool call requires user approval before executing.

    Short-circuits immediately to True when request_unredacted=True is present —
    the tool's own needs_approval is never consulted in that case. This is a hard
    gate: bypassing the redactor always requires explicit user permission, with no
    code path that can reach execution without it.

    Built-in tools should expose needs_approval(args, session_data=None,
    special_resources=None). special_resources carries framework-owned context
    such as approval_mode and the current session cwd. The fallback arity checks
    below are kept so older custom tools remain compatible.
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

    clean_args = {k: v for k, v in args.items() if k not in _RESERVED_TOOL_PARAMS}
    fn_special_resources = dict(special_resources or {})
    if _accepts_special_resources(fn):
        return bool(fn(clean_args, session_data, fn_special_resources))
    if _accepts_session_data(fn):
        return bool(fn(clean_args, session_data))
    return bool(fn(clean_args))


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
    """Return True if the tool function declares a third special_resources parameter."""
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
    # both opted into redaction and allows the bypass. All three conditions must
    # hold — a tool with ENABLE_REDACTION=False never had anything to bypass, and
    # ALLOW_REQUEST_UNREDACTED=False means bypass is impossible even if requested.
    enable_redaction = bool(getattr(module, "ENABLE_REDACTION", False))
    allow_unredacted = bool(getattr(module, "ALLOW_REQUEST_UNREDACTED", True))
    requested_unredacted = bool(args.get("request_unredacted"))
    bypass_redaction = enable_redaction and allow_unredacted and requested_unredacted

    # Strip framework-managed params before validation and execution so tool code
    # never sees them and validate_tool_args doesn't reject them as extra properties.
    clean_args = {k: v for k, v in args.items() if k not in _RESERVED_TOOL_PARAMS}

    try:
        validate_tool_args(module.DEFINITION, clean_args)
        fn = module.execute
        if special_resources is not None and _accepts_special_resources(fn):
            # Pass a fresh copy (never mutate the caller's dict, which is reused
            # across every tool call in the turn) carrying the resolved bypass
            # decision. Tools that write raw content into session memory as a
            # side effect (not via their return value) use this to redact that
            # write themselves — the central redaction below only ever sees
            # their return value, not memory side effects.
            fn_special_resources = dict(special_resources)
            fn_special_resources["request_unredacted"] = bypass_redaction
            result = fn(clean_args, session_data, fn_special_resources)
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

    # Column truncation is applied last, AFTER redaction, so that secrets are
    # detected/replaced against the full text and truncation can never split a
    # secret and leak a partial value.
    if not enable_redaction or bypass_redaction:
        return _truncate_columns(result)

    from src.redaction.core import redact as _redact

    _fp = args.get("path") or args.get("filepath") or None
    file_path = _fp if isinstance(_fp, str) else None
    return _truncate_columns(_redact(file_path, result))


# ---------------------------------------------------------------------------
# Custom tool plugins metadata (empty at server start; populated per-session)
# ---------------------------------------------------------------------------

_custom_tool_plugins: list[dict] = []

# ---------------------------------------------------------------------------
# Custom tool loading — called at session-creation time, not server start
# ---------------------------------------------------------------------------


@dataclass
class CustomToolLoadResult:
    """Result of load_custom_tools, grouped by activation scope.

    unscoped_defs/unscoped_map: tools loaded from .py files directly in
    tools_dir (no namespace prefix, always active regardless of skill
    selection).
    by_skill: skill_id -> (defs, tool_map) for each namespaced plugin
    folder — only active in a subturn where that skill id is active.
    """

    unscoped_defs: list[dict] = field(default_factory=list)
    unscoped_map: dict = field(default_factory=dict)
    by_skill: dict[str, tuple[list[dict], dict]] = field(default_factory=dict)
    plugins: list[dict] = field(default_factory=list)
    custom_exclusions: dict = field(default_factory=dict)


def _load_tool_module(tool_path: str, module_name: str) -> object | None:
    """Import a tool file as a fresh module.

    Returns the module, or None if it has no DEFINITION (a plain helper file,
    not a tool — it still executes, so a sibling file can `import` it, but it
    is dropped from sys.modules since it isn't itself a tool). Raises
    RuntimeError on any import failure or a DEFINITION without execute.
    """
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
        raise RuntimeError(f"Failed to import custom tool {tool_path!r}: {e}") from e

    if not hasattr(module, "DEFINITION"):
        sys.modules.pop(module_name, None)
        return None

    if not hasattr(module, "execute"):
        sys.modules.pop(module_name, None)
        raise RuntimeError(
            f"Custom tool {tool_path!r} has DEFINITION but is missing required function 'execute'."
        )
    return module


def _base_tool_name(module: object, tool_path: str) -> str:
    base_tool_name = module.DEFINITION.get("function", {}).get("name")
    if not base_tool_name:
        raise RuntimeError(
            f"Custom tool {tool_path!r} has a DEFINITION dict that is missing 'function.name'."
        )
    return base_tool_name


def _finalize_tool_def(
    module: object, tool_path: str, tool_name: str, all_seen_names: set[str]
) -> dict:
    """Validate a loaded tool module and build its final, framework-injected DEFINITION.

    Does not mutate all_seen_names — the caller adds tool_name on success.
    """
    if tool_name in all_seen_names:
        raise RuntimeError(
            f"Custom tool {tool_name!r} (from {tool_path!r}) collides with an existing tool."
            f" Rename the tool to resolve this collision."
        )

    raw_props = (
        module.DEFINITION.get("function", {})
        .get("parameters", {})
        .get("properties", {})
        or {}
    )
    for _reserved in _RESERVED_TOOL_PARAMS:
        if _reserved in raw_props:
            raise RuntimeError(
                f"Custom tool {tool_path!r} explicitly declares reserved parameter "
                f"'{_reserved}'. This parameter is managed by the framework and "
                "must not be defined in tool source code."
            )

    prefixed_def = _inject_framework_params(module, module.DEFINITION)
    prefixed_def["function"]["name"] = tool_name
    return prefixed_def


def load_custom_tools(
    tools_dir: str,
    workspace_root: str | None = None,
    session_prefix: str = "",
    known_skill_ids: frozenset[str] | None = None,
) -> CustomToolLoadResult:
    """
    Load custom tool plugins from tools_dir.

    Two categories of custom tools:
      - Unscoped: .py files directly in tools_dir. No namespace prefix,
        always active regardless of skill selection.
      - Skill-scoped: .py files inside a namespaced plugin folder
        (tools_dir/<plugin>/__init__.py + tool files). Namespace defaults to
        the plugin folder name; an explicit TOOL_NAMESPACE in __init__.py
        overrides it. If known_skill_ids is provided, the resolved namespace
        must be a member of it, or loading raises RuntimeError — every
        skill-scoped plugin must correspond to an active skill so its tools
        have a defined activation condition. Pass known_skill_ids=None to
        skip this check (e.g. tests that don't care about skill-gating).

    session_prefix is prepended to sys.modules keys to prevent collisions when
    multiple sessions load tools from the same path simultaneously.

    Raises RuntimeError on any loading error.
    """
    if not os.path.isdir(tools_dir):
        # No tools/ directory present — silently load nothing.
        return CustomToolLoadResult()

    if workspace_root and workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

    unscoped_defs: list[dict] = []
    unscoped_map: dict = {}
    by_skill_defs: dict[str, list[dict]] = {}
    by_skill_map: dict[str, dict] = {}
    plugins: list[dict] = []
    all_seen_names: set[str] = set(_TOOL_MAP.keys())

    _RESERVED_ROOT_FILES = {"__init__.py", "_exclude_builtin_tools.py"}

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
            excl_spec = importlib.util.spec_from_file_location(
                excl_module_name, exclude_file
            )
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

    # Unscoped tools: .py files directly in tools_dir, no namespace, always active.
    try:
        root_files = sorted(
            f
            for f in os.listdir(tools_dir)
            if f.lower().endswith(".py") and f not in _RESERVED_ROOT_FILES
        )
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f"Cannot list tools/ directory at {tools_dir!r}: {e}") from e

    for tool_file in root_files:
        tool_path = os.path.join(tools_dir, tool_file)
        stem = os.path.splitext(tool_file)[0]
        module_name = f"_slbp_{session_prefix}_{stem}"

        module = _load_tool_module(tool_path, module_name)
        if module is None:
            continue  # helper file, not a tool

        base_tool_name = _base_tool_name(module, tool_path)
        tool_name = base_tool_name  # unscoped: no namespace prefix

        try:
            prefixed_def = _finalize_tool_def(
                module, tool_path, tool_name, all_seen_names
            )
        except RuntimeError:
            sys.modules.pop(module_name, None)
            raise

        unscoped_defs.append(prefixed_def)
        unscoped_map[tool_name] = module
        all_seen_names.add(tool_name)

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

        explicit_namespace = getattr(init_module, "TOOL_NAMESPACE", None)
        if explicit_namespace is not None:
            if (
                not isinstance(explicit_namespace, str)
                or not explicit_namespace.strip()
            ):
                raise RuntimeError(
                    f"Plugin __init__.py at {plugin_init!r} declares TOOL_NAMESPACE, "
                    "but it must be a non-empty string."
                )
            tool_namespace = explicit_namespace
        else:
            # No explicit TOOL_NAMESPACE — default to the plugin folder name.
            tool_namespace = plugin_name

        if known_skill_ids is not None and tool_namespace not in known_skill_ids:
            raise RuntimeError(
                f"Custom tool plugin {plugin_dir!r} resolves to namespace {tool_namespace!r}, "
                f"which does not match any known skill id (built-in or custom). Every "
                f"skill-scoped tool plugin must correspond to an active skill so its tools "
                f"have a defined activation condition.\n"
                f"Fix by one of:\n"
                f"  - If these tools should always be available regardless of skill "
                f"selection, move the file(s) directly into {tools_dir!r} (no "
                f"subdirectory) instead of under a namespaced plugin folder.\n"
                f"  - Add a matching skill with id {tool_namespace!r} (a skill file can be "
                f"empty/placeholder content) so the namespace has something to attach to.\n"
                f"  - Rename the plugin folder (or its explicit TOOL_NAMESPACE) to match an "
                f"existing skill id."
            )

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
        skill_defs = by_skill_defs.setdefault(tool_namespace, [])
        skill_map = by_skill_map.setdefault(tool_namespace, {})

        for tool_file in plugin_files:
            tool_path = os.path.join(plugin_dir, tool_file)
            stem = os.path.splitext(tool_file)[0]
            module_name = f"_slbp_{session_prefix}_{tool_namespace}_{stem}"

            module = _load_tool_module(tool_path, module_name)
            if module is None:
                continue  # helper file, not a tool

            base_tool_name = _base_tool_name(module, tool_path)
            tool_name = f"{tool_namespace}_{base_tool_name}"

            try:
                prefixed_def = _finalize_tool_def(
                    module, tool_path, tool_name, all_seen_names
                )
            except RuntimeError:
                sys.modules.pop(module_name, None)
                raise

            skill_defs.append(prefixed_def)
            skill_map[tool_name] = module
            all_seen_names.add(tool_name)
            plugin_tool_count += 1

        plugins.append(
            {
                "name": plugin_name,
                "count": plugin_tool_count,
                "path": plugin_dir.replace("\\", "/"),
            }
        )

    by_skill = {ns: (by_skill_defs[ns], by_skill_map[ns]) for ns in by_skill_defs}
    return CustomToolLoadResult(
        unscoped_defs=unscoped_defs,
        unscoped_map=unscoped_map,
        by_skill=by_skill,
        plugins=plugins,
        custom_exclusions=custom_exclusions,
    )
