from __future__ import annotations

import copy
import json
import re

from src.tools._memory import ensure_session_memory
from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT = "KEEP"  # module-level fallback; per-action policy takes precedence

LEAVE_OUT_PER_ACTION = {
    "get":              ("SHORT",       500),
    "set":              ("PARAMS_ONLY", 0),
    "delete":           ("PARAMS_ONLY", 0),
    "list":             ("KEEP",        0),
    "append":           ("PARAMS_ONLY", 0),
    "concat":           ("PARAMS_ONLY", 0),
    "copy":             ("PARAMS_ONLY", 0),
    "rename":           ("PARAMS_ONLY", 0),
    "extract_json":     ("SHORT",       500),
    "search_by_regex":  ("SHORT",       500),
}

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory",
        "description": (
            "Manage session-scoped key-value memory. "
            "Actions: get, set, delete, list, append, concat, copy, rename, extract_json, search_by_regex."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "get", "set", "delete", "list",
                        "append", "concat", "copy", "rename", "extract_json",
                        "search_by_regex",
                    ],
                    "description": (
                        "The operation to perform:\n"
                        "  get              -- retrieve a value (optionally line-numbered).\n"
                        "  set              -- store a text value.\n"
                        "  delete           -- remove a key.\n"
                        "  list             -- list keys (optional prefix/limit/offset filter).\n"
                        "  append           -- append text to an existing key (creates if absent).\n"
                        "  concat           -- concatenate two keys into a destination key.\n"
                        "  copy             -- copy source_key to dest_key (source preserved).\n"
                        "  rename           -- move source_key to dest_key (source deleted).\n"
                        "  extract_json     -- parse a key as JSON and traverse a path.\n"
                        "  search_by_regex  -- search a key's value for lines matching a regex."
                    ),
                },
                "key": {
                    "type": "string",
                    "description": "Memory key. Used by: get, set, delete, append, extract_json, search_by_regex.",
                },
                "value": {
                    "type": "string",
                    "description": "Text value to store. Used by: set.",
                },
                "number_lines": {
                    "type": "boolean",
                    "description": "If true, return a line-numbered view. Used by: get.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to append. Used by: append.",
                },
                "key_a": {
                    "type": "string",
                    "description": "First source key. Used by: concat.",
                },
                "key_b": {
                    "type": "string",
                    "description": "Second source key. Used by: concat.",
                },
                "dest_key": {
                    "type": "string",
                    "description": "Destination key. Used by: concat, copy, rename.",
                },
                "source_key": {
                    "type": "string",
                    "description": "Source key. Used by: copy, rename.",
                },
                "force_overwrite": {
                    "type": "boolean",
                    "description": (
                        "If true, overwrite dest_key if it exists. "
                        "Default: false. Used by: copy, rename."
                    ),
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
                "path": {
                    "type": "string",
                    "description": (
                        "Dot-delimited JSON traversal path, e.g. 'results.0.name'. "
                        "Mutually exclusive with path_steps. Used by: extract_json."
                    ),
                },
                "path_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered traversal steps as an array of strings. "
                        "Use only when a JSON key contains a period. "
                        "Mutually exclusive with path. Used by: extract_json."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "'return_value' (default): return inline as a string. "
                        "'session_memory': write extracted value to output_key. "
                        "Used by: extract_json."
                    ),
                },
                "output_key": {
                    "type": "string",
                    "description": (
                        "Destination session memory key for the extracted value. "
                        "Required when target='session_memory'. Used by: extract_json."
                    ),
                },
                "enable_interpret_data": {
                    "type": "boolean",
                    "description": (
                        "Default true. When true, strings are returned as plain text; "
                        "other types as indented JSON. When false, always raw json.dumps. "
                        "Used by: extract_json."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": "Python regular expression to search for. Used by: search_by_regex.",
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

def _value_to_str(value, interpret: bool) -> str:
    if interpret and isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _traverse(value, steps: list[str]):
    """Traverse value along steps. Returns (result, error_message)."""
    for i, step in enumerate(steps):
        if isinstance(value, list):
            try:
                idx = int(step)
            except ValueError:
                return None, (
                    f"Error: at step {i} the current value is a list, "
                    f"but step {step!r} is not a valid integer index."
                )
            if idx < -len(value) or idx >= len(value):
                return None, (
                    f"Error: at step {i} index {idx} is out of range "
                    f"(list length {len(value)})."
                )
            value = value[idx]
        elif isinstance(value, dict):
            if step not in value:
                return None, (
                    f"Error: at step {i} key {step!r} not found. "
                    f"Available keys: {list(value.keys())!r}"
                )
            value = value[step]
        else:
            return None, (
                f"Error: at step {i} the current value is {type(value).__name__!r} "
                f"(not a dict or list), cannot traverse further with step {step!r}."
            )
    return value, None


# ---- action implementations --------------------------------------------------

def _do_get(args: dict, memory: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'get'."
    value = memory.get(key)
    if args.get("number_lines"):
        if not isinstance(value, str):
            return f"Error: key {key!r} does not hold a text value."
        return add_line_numbers(value, start_line=1)
    if value is None:
        return f"(key {key!r} not found)"
    return value if isinstance(value, str) else str(value)


def _do_set(args: dict, memory: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'set'."
    value = args.get("value")
    if value is None:
        return "Error: 'value' is required for action 'set'."
    if not isinstance(value, str):
        return f"Error: value must be a plain string, got {type(value).__name__}."
    memory[key] = value
    return f"Stored value at key {key!r}."


def _do_delete(args: dict, memory: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'delete'."
    if key not in memory:
        raise ValueError(f"Key {key!r} does not exist in session memory.")
    del memory[key]
    return f"Deleted key {key!r}."


def _do_list(args: dict, memory: dict) -> str:
    prefix = args.get("prefix")
    offset = int(args.get("offset", 0))
    limit = args.get("limit")
    if limit is not None:
        limit = int(limit)
    keys = sorted(memory.keys())
    if prefix is not None:
        keys = [k for k in keys if k.startswith(prefix)]
    if offset:
        keys = keys[offset:]
    if limit is not None:
        keys = keys[:limit]
    return "\n".join(keys)


def _do_append(args: dict, memory: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'append'."
    text = args.get("text")
    if text is None:
        return "Error: 'text' is required for action 'append'."
    existing = memory.get(key)
    if existing is not None and not isinstance(existing, str):
        return f"Error: key {key!r} does not hold a text value."
    memory[key] = (existing or "") + text
    return f"Appended text to {key}"


def _do_concat(args: dict, memory: dict) -> str:
    key_a = args.get("key_a")
    key_b = args.get("key_b")
    dest_key = args.get("dest_key")
    if not key_a or not key_b or not dest_key:
        return "Error: 'key_a', 'key_b', and 'dest_key' are required for action 'concat'."
    value_a = memory.get(key_a)
    value_b = memory.get(key_b)
    if value_a is not None and not isinstance(value_a, str):
        return f"Error: key {key_a!r} does not hold a text value."
    if value_b is not None and not isinstance(value_b, str):
        return f"Error: key {key_b!r} does not hold a text value."
    memory[dest_key] = (value_a or "") + (value_b or "")
    return f"Concatted {key_a} and {key_b} and saved to {dest_key}"


def _do_copy(args: dict, memory: dict) -> str:
    source_key = args.get("source_key")
    dest_key = args.get("dest_key")
    if not source_key or not dest_key:
        return "Error: 'source_key' and 'dest_key' are required for action 'copy'."
    force_overwrite = bool(args.get("force_overwrite", False))
    if source_key not in memory:
        return f"Error: source key {source_key!r} not found in session memory."
    if dest_key in memory and not force_overwrite:
        return (
            f"Error: destination key {dest_key!r} already exists in session memory. "
            "Use force_overwrite=true to overwrite."
        )
    memory[dest_key] = copy.deepcopy(memory[source_key])
    return f"Copied session memory key {source_key!r} to {dest_key!r}."


def _do_rename(args: dict, memory: dict) -> str:
    source_key = args.get("source_key")
    dest_key = args.get("dest_key")
    if not source_key or not dest_key:
        return "Error: 'source_key' and 'dest_key' are required for action 'rename'."
    force_overwrite = bool(args.get("force_overwrite", False))
    if source_key not in memory:
        return f"Error: source key {source_key!r} not found in session memory."
    if dest_key in memory and not force_overwrite:
        return (
            f"Error: destination key {dest_key!r} already exists in session memory. "
            "Use force_overwrite=true to overwrite."
        )
    memory[dest_key] = copy.deepcopy(memory[source_key])
    del memory[source_key]
    return f"Renamed session memory key {source_key!r} to {dest_key!r}."


def _do_extract_json(args: dict, memory: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'extract_json'."
    has_path = "path" in args and args["path"] is not None
    has_steps = "path_steps" in args and args["path_steps"] is not None
    target = args.get("target", "return_value")
    interpret = args.get("enable_interpret_data", True)

    if has_path and has_steps:
        return "Error: provide either 'path' or 'path_steps', not both."
    if not has_path and not has_steps:
        return "Error: one of 'path' or 'path_steps' must be provided."

    if has_path:
        steps = args["path"].split(".")
        path_repr = args["path"]
    else:
        steps = args["path_steps"]
        path_repr = repr(steps)

    raw = memory.get(key)
    if raw is None:
        return f"Error: session memory key {key!r} not found."
    if not isinstance(raw, str):
        return f"Error: session memory key {key!r} does not hold a text value."

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"Error: failed to parse {key!r} as JSON: {e}"

    value, err = _traverse(value, steps)
    if err:
        return err

    if target == "session_memory":
        out_key = args.get("output_key")
        if not out_key:
            return "Error: target='session_memory' requires output_key."
        memory[out_key] = _value_to_str(value, interpret)
        return (
            f"Extracted value from {key!r} at path {path_repr!r} "
            f"and stored it in session memory key {out_key!r}."
        )

    return _value_to_str(value, interpret)


_BOLD = "\033[1m"
_RESET = "\033[0m"


def _highlight(line: str, pattern: str) -> str:
    try:
        return re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
    except re.error:
        return line


def _do_search_by_regex(args: dict, memory: dict) -> str:
    key = args.get("key")
    if not key:
        return "Error: 'key' is required for action 'search_by_regex'."
    pattern = args.get("pattern")
    if not pattern:
        return "Error: 'pattern' is required for action 'search_by_regex'."
    value = memory.get(key)
    if value is None:
        return f"(key {key!r} not found)"
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
    "append": _do_append,
    "concat": _do_concat,
    "copy": _do_copy,
    "rename": _do_rename,
    "extract_json": _do_extract_json,
    "search_by_regex": _do_search_by_regex,
}


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)
    action = args.get("action")
    fn = _ACTION_MAP.get(action)
    if fn is None:
        return f"Error: unknown action {action!r}."
    return fn(args, memory)
