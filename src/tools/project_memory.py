from __future__ import annotations

import os
import re

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT = "KEEP"  # module-level fallback; per-action policy takes precedence

LEAVE_OUT_PER_ACTION = {
    "get":    ("SHORT",       500),
    "set":    ("PARAMS_ONLY", 0),
    "delete": ("PARAMS_ONLY", 0),
    "list":   ("KEEP",        0),
    "search": ("SHORT",       500),
}

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "project_memory",
        "description": (
            "Manage persistent project-scoped key-value memory. "
            "Project memory persists across sessions and is scoped to a project path. "
            "Actions: get, set, delete, list, search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "delete", "list", "search"],
                    "description": (
                        "The operation to perform:\n"
                        "  get    -- retrieve a value (inline or into session memory).\n"
                        "  set    -- store a value (literal string or from session memory).\n"
                        "  delete -- remove a key.\n"
                        "  list   -- list keys (optional prefix/limit/offset filter).\n"
                        "  search -- search a value for lines matching a regex."
                    ),
                },
                "key": {
                    "type": "string",
                    "description": "Project memory key. Used by: get, set, delete, search.",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional filesystem path identifying the project scope. "
                        "Defaults to the pinned initial working directory (or current "
                        "working directory if pinning is disabled). Used by: all actions."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Literal text value to store. "
                        "Mutually exclusive with from_session_key. Used by: set."
                    ),
                },
                "from_session_key": {
                    "type": "string",
                    "description": (
                        "Copy the value from this session memory key into project memory. "
                        "Mutually exclusive with value. "
                        "Use this after editing content in session memory to persist it. "
                        "Used by: set."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "'return_value' (default): return the value inline. "
                        "'session_memory': write the value into target_session_key. "
                        "Useful for large values you want to manipulate with session memory tools. "
                        "Used by: get."
                    ),
                },
                "target_session_key": {
                    "type": "string",
                    "description": (
                        "Required when target='session_memory'. "
                        "The session memory key to write the fetched value into. "
                        "Used by: get."
                    ),
                },
                "number_lines": {
                    "type": "boolean",
                    "description": (
                        "If true, return a line-numbered view of the value. "
                        "Only applies when target='return_value'. Used by: get."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": "Python regular expression to search for. Used by: search.",
                },
                "prefix": {
                    "type": "string",
                    "description": "Optional key prefix filter. Used by: list.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Maximum number of keys to return. Used by: list.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Pagination offset. Used by: list.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


# ---- helpers -----------------------------------------------------------------

_BOLD = "\033[1m"
_RESET = "\033[0m"


def _get_project(args: dict, session_data: dict) -> str:
    explicit = args.get("project")
    if explicit:
        return explicit
    pinned = (session_data or {}).get("__pinned_project__")
    if pinned:
        return pinned
    return os.getcwd()


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def _highlight(line: str, pattern: str) -> str:
    try:
        return re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    except re.error:
        return line


# ---- action implementations --------------------------------------------------

def _do_get(args: dict, session_data: dict, special_resources: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'get'."
    project = _get_project(args, session_data)
    target = args.get("target", "return_value")

    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)

    if value is None:
        return f"(key {key!r} not found in project memory)"

    if target == "session_memory":
        session_key = args.get("target_session_key")
        if not session_key:
            return "Error: target='session_memory' requires target_session_key."
        memory = _ensure_session_memory(session_data)
        memory[session_key] = value
        return f"Loaded project memory key {key!r} into session memory key {session_key!r}."

    if args.get("number_lines"):
        if not isinstance(value, str):
            return f"Error: key {key!r} does not hold a text value."
        return add_line_numbers(value, start_line=1)

    return value


def _do_set(args: dict, session_data: dict, special_resources: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'set'."
    project = _get_project(args, session_data)

    has_value = "value" in args
    has_from = "from_session_key" in args

    if has_value and has_from:
        return "Error: provide either 'value' or 'from_session_key', not both."
    if not has_value and not has_from:
        return "Error: provide either 'value' or 'from_session_key'."

    if has_from:
        session_key = args["from_session_key"]
        memory = (session_data or {}).get("memory", {})
        if not isinstance(memory, dict) or session_key not in memory:
            return f"Error: session memory key {session_key!r} not found."
        text = memory[session_key]
        if not isinstance(text, str):
            return f"Error: session memory key {session_key!r} does not hold a text value."
    else:
        text = args["value"]
        if not isinstance(text, str):
            return f"Error: value must be a plain string, got {type(text).__name__}."

    emitting_kv = (special_resources or {}).get("emitting_kv_manager")
    if emitting_kv:
        emitting_kv.set_value(key, text, project=project)
    else:
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn).set_value(key, text, project=project)
            conn.commit()

    return f"Stored value at project memory key {key!r}."


def _do_delete(args: dict, session_data: dict, special_resources: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'delete'."
    project = _get_project(args, session_data)

    emitting_kv = (special_resources or {}).get("emitting_kv_manager")
    if emitting_kv:
        existed = emitting_kv.delete_value(key, project=project)
    else:
        pool = get_pool()
        with pool.get_connection() as conn:
            manager = KVManager(conn)
            existed = manager.exists(key, project=project)
            manager.delete_value(key, project=project)
            conn.commit()

    if not existed:
        raise ValueError(f"Key {key!r} does not exist in project memory.")
    return f"Deleted project memory key {key!r}."


def _do_list(args: dict, session_data: dict, special_resources: dict) -> str:
    project = _get_project(args, session_data)
    prefix = args.get("prefix")
    offset = int(args.get("offset", 0))
    limit = args.get("limit")
    if limit is not None:
        limit = int(limit)

    pool = get_pool()
    with pool.get_connection() as conn:
        keys = KVManager(conn).list_keys(
            project=project,
            prefix=prefix,
            limit=limit,
            offset=offset,
        )

    if not keys:
        return "(no keys found)"
    return "\n".join(keys)


def _do_search(args: dict, session_data: dict, special_resources: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'search'."
    pattern = args.get("pattern")
    if not pattern:
        return "Error: 'pattern' is required for action 'search'."
    project = _get_project(args, session_data)

    pool = get_pool()
    with pool.get_connection() as conn:
        value = KVManager(conn).get_value(key, project=project)

    if value is None:
        return f"(key {key!r} not found in project memory)"
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}"

    lines = value.splitlines(keepends=False)
    total = len(lines)
    if total == 0:
        return f"Key {key!r} is empty -- no matches."

    line_no_width = len(str(total))
    matches: list[str] = []

    for i, line in enumerate(lines, start=1):
        if compiled.search(line):
            lineno = str(i).rjust(line_no_width)
            highlighted = _highlight(line, pattern)
            matches.append(f"{lineno} | {highlighted}")

    if not matches:
        return f"No matches found in {key!r}."

    return f"{len(matches)} match(es) in {key!r}:\n" + "\n".join(matches)


# ---- dispatch ---------------------------------------------------------------

_ACTION_MAP = {
    "get": _do_get,
    "set": _do_set,
    "delete": _do_delete,
    "list": _do_list,
    "search": _do_search,
}


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    if special_resources is None:
        special_resources = {}
    action = args.get("action")
    fn = _ACTION_MAP.get(action)
    if fn is None:
        return f"Error: unknown action {action!r}."
    return fn(args, session_data, special_resources)
