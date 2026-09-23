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
from src.config.tool_execution import MAX_TOOL_DELEGATION_HOPS
from src.utils.text_truncation import truncate_long_lines
from src.tools._custom_tool_reload import reload_modules


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


def _exec_module_source(module: object, path: str) -> None:
    """Execute current source bytes directly, bypassing timestamp-based pyc reuse."""
    with open(path, "rb") as source_file:
        code = compile(source_file.read(), path, "exec")
    exec(code, module.__dict__)


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
            _exec_module_source(module, path)
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


# ---------------------------------------------------------------------------
# Tool wrapping: NextTool delegation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NextTool:
    """Returned by needs_approval/dirty_effects/execute instead of their normal
    terminal value (bool/dict/str) to mean "resolve this by delegating to
    another tool call instead." See custom_tool_guide.md's wrapping section.
    """

    name: str
    args: dict


class ToolDelegationError(RuntimeError):
    """A NextTool chain is broken: unknown target, a cycle, too many hops, or
    two of the three chains (needs_approval/dirty_effects/execute) disagreeing
    about where to delegate at the same step. Always carries a specific,
    actionable message — never a bare/generic one.
    """


def _walk_delegation_chain(start_name, start_args, tool_map, call_fn):
    """Follow a NextTool chain to its terminal value.

    call_fn(module, args) returns the hop's raw result — a terminal value
    (whatever type the caller cares about) or a NextTool to keep going.
    Returns (terminal_value, hop_path), where hop_path is the full list of
    NextTool(name, args) visited, starting with the original call (hop 0).
    Comparing two hop_paths element-by-element (NextTool has dataclass
    equality on name+args) is what the cross-chain divergence check uses.
    """
    hop_path: list[NextTool] = [NextTool(start_name, start_args)]
    visited: set[str] = {start_name}
    current_name, current_args = start_name, start_args

    while True:
        module = tool_map.get(current_name)
        if module is None:
            raise ToolDelegationError(
                f"NextTool delegation chain (starting at {start_name!r}) references "
                f"unknown tool {current_name!r}. Check for a typo, or a missing "
                "plugin/skill load."
            )

        result = call_fn(module, current_args)
        if not isinstance(result, NextTool):
            return result, hop_path

        if result.name in visited:
            raise ToolDelegationError(
                f"NextTool delegation cycle detected (starting at {start_name!r}): "
                f"{result.name!r} was reached twice in one chain. Cyclic delegation "
                "is never legitimate here (there is no eager/lazy evaluation to make "
                "revisiting a tool meaningful) — check the delegating tool's logic."
            )
        if len(hop_path) >= MAX_TOOL_DELEGATION_HOPS:
            raise ToolDelegationError(
                f"NextTool delegation chain (starting at {start_name!r}) exceeded "
                f"the maximum of {MAX_TOOL_DELEGATION_HOPS} hops "
                f"(src.config.tool_execution.MAX_TOOL_DELEGATION_HOPS) while trying "
                f"to reach {result.name!r}. This usually means an unintentionally "
                "long or effectively-cyclic delegation chain — check each tool's "
                "needs_approval/dirty_effects/execute for where it delegates."
            )

        visited.add(result.name)
        hop_path.append(result)
        current_name, current_args = result.name, result.args


def _check_hop_paths_agree(named_paths: dict) -> None:
    """Cross-check hop paths from different chains (needs_approval/dirty_effects/
    execute) that were all resolved for the SAME top-level tool call.

    Whenever two chains are both still delegating (both have a NextTool) at
    the same step, their target must match exactly (name AND args) — this is
    what stops a wrapper whose approval decision doesn't correspond to what it
    actually executes. Raises on the first mismatch found.
    """
    items = list(named_paths.items())
    for i in range(len(items)):
        label_i, path_i = items[i]
        for j in range(i + 1, len(items)):
            label_j, path_j = items[j]
            for k in range(min(len(path_i), len(path_j))):
                if path_i[k] != path_j[k]:
                    raise ToolDelegationError(
                        f"NextTool delegation mismatch at hop {k}: the {label_i!r} "
                        f"chain delegates to {path_i[k].name!r} (args={path_i[k].args!r}) "
                        f"while the {label_j!r} chain delegates to "
                        f"{path_j[k].name!r} (args={path_j[k].args!r}). "
                        "needs_approval/dirty_effects/execute must delegate to the "
                        "exact same tool and args whenever more than one of them is "
                        "still delegating at the same step — this is a hard error to "
                        "prevent a wrapper's approval/dirty-tracking from silently "
                        "diverging from what it actually executes."
                    )


def check_needs_approval(
    name: str,
    args: dict,
    tool_map: dict | None = None,
    session_data: dict | None = None,
    special_resources: dict | None = None,
) -> tuple[bool, list["NextTool"]]:
    """Return (needs_approval, hop_path) for this tool call.

    Short-circuits immediately to (True, [NextTool(name, args)]) when
    request_unredacted=True is present — the tool's own needs_approval is
    never consulted in that case. This is a hard gate: bypassing the
    redactor always requires explicit user permission, with no code path
    that can reach execution without it.

    Otherwise follows needs_approval's NextTool chain (see
    custom_tool_guide.md's wrapping section) — a tool with no needs_approval
    of its own (at any hop) terminates the chain at False. Built-in tools
    should expose needs_approval(args, session_data=None,
    special_resources=None); the fallback arity checks below keep older
    custom tools compatible.
    """
    # Hard gate: request_unredacted=True forces approval unconditionally.
    # Do NOT call the tool's needs_approval — the answer is already True.
    if args.get("request_unredacted"):
        return True, [NextTool(name, args)]

    actual_map = tool_map if tool_map is not None else _TOOL_MAP

    def _call(module, hop_args):
        # request_unredacted can also appear partway through a chain (a hop's
        # own constructed delegation args) — same hard gate, re-checked per hop.
        if hop_args.get("request_unredacted"):
            return True
        fn = getattr(module, "needs_approval", None)
        if fn is None:
            return False
        clean_args = {
            k: v for k, v in hop_args.items() if k not in _RESERVED_TOOL_PARAMS
        }
        fn_special_resources = dict(special_resources or {})
        if _accepts_special_resources(fn):
            result = fn(clean_args, session_data, fn_special_resources)
        elif _accepts_session_data(fn):
            result = fn(clean_args, session_data)
        else:
            result = fn(clean_args)
        if isinstance(result, NextTool):
            return result
        return bool(result)

    return _walk_delegation_chain(name, args, actual_map, _call)


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
) -> tuple[dict, list["NextTool"]]:
    """Return (dirty_effects, hop_path) for a tool call — {} if the tool (at
    the terminal hop) defines none. Follows dirty_effects's NextTool chain
    like the other two — see custom_tool_guide.md's wrapping section.
    """
    actual_map = tool_map if tool_map is not None else _TOOL_MAP

    def _call(module, hop_args):
        fn = getattr(module, "dirty_effects", None)
        if fn is None:
            return {}
        if session_data is not None and _accepts_session_data(fn):
            result = fn(hop_args, session_data)
        else:
            result = fn(hop_args)
        if isinstance(result, NextTool):
            return result
        return result or {}

    try:
        return _walk_delegation_chain(name, args, actual_map, _call)
    except ToolDelegationError:
        raise
    except Exception:
        return {}, [NextTool(name, args)]


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
) -> tuple[str, list["NextTool"]]:
    """Execute a tool call, following its execute's NextTool chain if any.

    Returns (result, hop_path). Redaction/bypass/NO_STUB are decided using
    the STRICTEST value seen across every hop in the chain, never loosened
    by a later hop — see custom_tool_guide.md's wrapping section. This is
    what makes wrapping safe by default: a wrapper around a redacted tool
    redacts even if the wrapper's own module never declares ENABLE_REDACTION.
    NO_STUB is computed by the caller (tool_execution.py) from the returned
    hop_path, since stubbing is applied outside execute_tool.
    """
    actual_map = tool_map if tool_map is not None else _TOOL_MAP
    if session_data is None:
        session_data = {}

    # Accumulated monotonically across hops — see the module docstring above.
    # enable_redaction/allow_unredacted only ever get MORE restrictive;
    # requested_unredacted is an OR (asked for anywhere in the chain counts).
    redaction_state = {
        "enable_redaction": False,
        "allow_unredacted": True,
        "requested_unredacted": False,
    }

    def _call(module, hop_args):
        redaction_state["enable_redaction"] = redaction_state[
            "enable_redaction"
        ] or bool(getattr(module, "ENABLE_REDACTION", False))
        redaction_state["allow_unredacted"] = redaction_state[
            "allow_unredacted"
        ] and bool(getattr(module, "ALLOW_REQUEST_UNREDACTED", True))
        redaction_state["requested_unredacted"] = redaction_state[
            "requested_unredacted"
        ] or bool(hop_args.get("request_unredacted"))
        bypass_so_far = (
            redaction_state["enable_redaction"]
            and redaction_state["allow_unredacted"]
            and redaction_state["requested_unredacted"]
        )

        # Strip framework-managed params before validation/execution so tool
        # code never sees them and validate_tool_args doesn't reject them as
        # extra properties.
        clean_args = {
            k: v for k, v in hop_args.items() if k not in _RESERVED_TOOL_PARAMS
        }
        validate_tool_args(module.DEFINITION, clean_args)

        fn = module.execute
        if special_resources is not None and _accepts_special_resources(fn):
            # Fresh copy per hop (never mutate the caller's dict, which is
            # reused across every tool call in the turn) carrying the
            # best-known-so-far bypass decision. This is informational for
            # this hop's own execute() (e.g. tools that redact a session-
            # memory side effect themselves) — the actual redaction of the
            # RETURNED string happens once, after the full chain resolves,
            # using the final (fully strict) values, not this per-hop signal.
            fn_special_resources = dict(special_resources)
            fn_special_resources["request_unredacted"] = bypass_so_far
            result = fn(clean_args, session_data, fn_special_resources)
        else:
            result = fn(clean_args, session_data)
        return result

    try:
        result, hop_path = _walk_delegation_chain(name, args, actual_map, _call)
    except (ToolHangError, ToolTimeoutError):
        raise
    except Exception as e:
        if os.environ.get("SLBP_TOOL_TRACEBACKS") == "1":
            tb = traceback.format_exc()
            result = f"Failed to execute tool {name}:\n{tb}".rstrip()
        else:
            result = f"Failed to execute tool {name}:\n{e}"
        return _truncate_columns(result), [NextTool(name, args)]

    enable_redaction = redaction_state["enable_redaction"]
    bypass_redaction = (
        enable_redaction
        and redaction_state["allow_unredacted"]
        and redaction_state["requested_unredacted"]
    )

    # Column truncation is applied last, AFTER redaction, so that secrets are
    # detected/replaced against the full text and truncation can never split a
    # secret and leak a partial value.
    if not enable_redaction or bypass_redaction:
        return _truncate_columns(result), hop_path

    from src.redaction.core import redact as _redact

    _fp = args.get("path") or args.get("filepath") or None
    file_path = _fp if isinstance(_fp, str) else None
    return _truncate_columns(_redact(file_path, result)), hop_path


def extend_tool_definition(
    original: dict, new: dict, remove_keys: list[str] | None = None
) -> dict:
    """Pure function: build a wrapper's DEFINITION by extending a wrapped
    tool's DEFINITION with overrides, optionally dropping some parameters.

    Never mutates `original` or `new` — always deep-copies first. This
    matters: `original` is very often a shared, module-level DEFINITION dict
    (e.g. a built-in tool's `DEFINITION`), reused by every session/thread in
    the process — mutating it in place would corrupt it for everyone,
    permanently.

    Merge rules:
      - top-level `type`: `new`'s value if present, else `original`'s
        (defaults to "function").
      - `function.name`/`function.description`: `new`'s value if present,
        else `original`'s.
      - `function.parameters.properties`: shallow-merged — keys present in
        `new` override/add, every key not mentioned in `new` is kept from
        `original`.
      - `function.parameters.required`/`additionalProperties`/`type`: `new`'s
        value if present (replaces entirely), else `original`'s.
      - `remove_keys` is applied last: popped from the merged `properties`,
        and stripped from the merged `required` list.
    """
    result = copy.deepcopy(original)
    new = copy.deepcopy(new)

    if "type" in new:
        result["type"] = new["type"]
    else:
        result.setdefault("type", "function")

    result_fn = result.setdefault("function", {})
    new_fn = new.get("function", {})

    if "name" in new_fn:
        result_fn["name"] = new_fn["name"]
    if "description" in new_fn:
        result_fn["description"] = new_fn["description"]

    result_params = result_fn.setdefault(
        "parameters", {"type": "object", "properties": {}}
    )
    new_params = new_fn.get("parameters", {})

    if "type" in new_params:
        result_params["type"] = new_params["type"]
    if "additionalProperties" in new_params:
        result_params["additionalProperties"] = new_params["additionalProperties"]

    result_props = result_params.setdefault("properties", {})
    result_props.update(new_params.get("properties", {}))

    if "required" in new_params:
        result_params["required"] = list(new_params["required"])

    for key in remove_keys or []:
        result_props.pop(key, None)
        if "required" in result_params and key in result_params["required"]:
            result_params["required"] = [
                r for r in result_params["required"] if r != key
            ]

    return result


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
        _exec_module_source(module, tool_path)
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
            _exec_module_source(tools_init_module, tools_init)
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
            _exec_module_source(excl_module, exclude_file)
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
            _exec_module_source(init_module, plugin_init)
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


def reload_custom_tools(
    tools_dir: str,
    workspace_root: str | None = None,
    session_prefix: str = "",
    known_skill_ids: frozenset[str] | None = None,
) -> CustomToolLoadResult:
    """Reload one session's custom tools while preserving its prior modules on error.

    Modules loaded from ``tools_dir`` include tool files, package initializers,
    and helpers imported through either normal Python imports or ``import_local``.
    They must all leave ``sys.modules`` before loading so changed source is
    executed. Existing tool maps retain references to their old module objects,
    which lets us restore the module cache if validation of the new generation
    fails.
    """

    return reload_modules(
        tools_dir=tools_dir,
        session_prefix=session_prefix,
        load=lambda: load_custom_tools(
            tools_dir=tools_dir,
            workspace_root=workspace_root,
            session_prefix=session_prefix,
            known_skill_ids=known_skill_ids,
        ),
    )
