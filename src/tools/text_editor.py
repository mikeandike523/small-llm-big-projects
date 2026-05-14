from __future__ import annotations

import re
from io import StringIO

from src.tools._eol import EOL_CHOICES, check_eol, normalize_eol
from src.tools._indentation import (
    INDENT_TARGET_CHOICES,
    DEFAULT_SPACES_PER_TAB,
    check_indentation,
    convert_indentation,
)
from src.tools._memory import ensure_session_memory
from src.tools._text_editor_utils import (
    _apply_edits,
    _count_lines,
    _make_diff,
    _split_lines_preserve,
    _detect_newline_style,
    _parse_simple_edit,
)
from src.utils.text.line_numbers import add_line_numbers

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "text_editor",
        "description": (
            "Structural text-editor operations on a session memory string value OR directly on a file on disk. "
            "Provide exactly one of: 'key' (session memory key) or 'filepath' (path to a file on disk). "
            "When 'filepath' is given the file is read into a temporary buffer, the operation is applied, "
            "and (for write actions) the result is written back atomically. "
            "filepath uses the same approval gating as write_text_file. "
            "\n\n"
            "LINE ENDING RULES:\n"
            "Only LF (\\n) and CRLF (\\r\\n) are recognised as line terminators. "
            "Bare \\r is treated as a regular character and is never split on or converted. "
            "apply_patch re-encodes the result to match the existing EOL style (CRLF if any CRLF "
            "present, else LF); set disable_auto_eol=true to suppress. "
            "\n\n"
            "Actions: read_lines, search_by_regex, count_lines, "
            "check_eol, normalize_eol, check_indentation, convert_indentation, apply_patch."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "read_lines",
                        "search_by_regex",
                        "count_lines",
                        "check_eol",
                        "normalize_eol",
                        "check_indentation",
                        "convert_indentation",
                        "apply_patch",
                    ],
                    "description": (
                        "The operation to perform:\n"
                        "  read_lines          -- read all or a line range (1-based inclusive).\n"
                        "  search_by_regex     -- search for lines matching a regex; returns matching lines with line numbers.\n"
                        "  count_lines         -- count total lines.\n"
                        "  check_eol           -- report line-ending style statistics.\n"
                        "  normalize_eol       -- normalize all line endings to a single style.\n"
                        "  check_indentation   -- report indentation style statistics.\n"
                        "  convert_indentation -- convert leading-whitespace indentation style.\n"
                        "  apply_patch         -- apply a list of edits (see 'edits' parameter). "
                        "Each edit locates itself by content search; no line numbers required. "
                        "Auto-matches EOL style."
                    ),
                },
                "key": {
                    "type": "string",
                    "description": (
                        "Session memory key. Must hold a text value. "
                        "Mutually exclusive with 'filepath'. Provide exactly one."
                    ),
                },
                "filepath": {
                    "type": "string",
                    "description": (
                        "Path to a file on disk (relative or absolute). "
                        "The file is read, the operation is applied, and (for write actions) the result is written back. "
                        "Requires the same approval as write_text_file. "
                        "Mutually exclusive with 'key'. Provide exactly one."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based start line (inclusive). Used by: read_lines.",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based end line (inclusive). Used by: read_lines.",
                },
                "number_lines": {
                    "type": "boolean",
                    "description": "If true, prefix each returned line with its line number. Used by: read_lines.",
                },
                "delimiter": {
                    "type": "string",
                    "description": (
                        "Separator between line number and content when number_lines is true. "
                        "Defaults to ' | '. Used by: read_lines."
                    ),
                },
                "disable_auto_eol": {
                    "type": "boolean",
                    "description": (
                        "If true, skip automatic EOL style normalisation for apply_patch and write verbatim. "
                        "By default (false), apply_patch re-encodes the result to match the existing "
                        "EOL style: CRLF if any CRLF present, else LF. "
                        "Used by: apply_patch."
                    ),
                },
                "trailing_newline": {
                    "type": "boolean",
                    "description": (
                        "Override trailing-newline behaviour for apply_patch. "
                        "Omit (default) to preserve the original file's trailing newline state. "
                        "true = always end result with a newline. "
                        "false = always strip trailing newline. "
                        "Useful for data files (e.g. flashcard decks, CSV) expected to have no trailing newline. "
                        "Used by: apply_patch."
                    ),
                },
                "eol": {
                    "type": "string",
                    "enum": EOL_CHOICES,
                    "description": (
                        "Target line-ending style: 'lf' (\\n), 'crlf' (\\r\\n), or 'cr' (\\r). "
                        "Used by: normalize_eol."
                    ),
                },
                "to": {
                    "type": "string",
                    "enum": INDENT_TARGET_CHOICES,
                    "description": "Target indentation style: 'tabs' or 'spaces'. Used by: convert_indentation.",
                },
                "spaces_per_tab": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        f"Number of spaces per tab stop (used in both directions). "
                        f"Default: {DEFAULT_SPACES_PER_TAB}. Used by: convert_indentation."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": "Python regular expression to search for. Used by: search_by_regex.",
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": (
                                    "The edit block. Each line is prefixed with:\n"
                                    "  '+'  add this line\n"
                                    "  '-'  remove this line\n"
                                    "  ' '  (space) context line -- must exist unchanged; used to locate the edit\n"
                                    "Lines with no prefix are also treated as context. "
                                    "Always surround every change with at least one context line above and below -- "
                                    "a block with only '+' lines and no '-' or context has nothing to anchor on "
                                    "and requires 'position' to be set."
                                ),
                            },
                            "position": {
                                "type": "integer",
                                "minimum": 1,
                                "description": (
                                    "1-based line number. Used ONLY when the edit has no context or removed lines "
                                    "(pure insertion of '+' lines only). In all other cases the edit is anchored "
                                    "by content search and 'position' is ignored."
                                ),
                            },
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    "description": "List of edits to apply sequentially. Used by: apply_patch.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Approval gating
# ---------------------------------------------------------------------------


_WRITE_ACTIONS_SET = {
    "normalize_eol",
    "convert_indentation",
    "apply_patch",
}


def dirty_effects(args: dict, session_data: dict | None = None) -> dict:
    action = args.get("action", "")
    filepath = args.get("filepath")
    key = args.get("key")

    if action in _WRITE_ACTIONS_SET:
        if filepath:
            return {"requires_clean_files": [filepath], "dirties_files": [filepath]}
        if key:
            return {"requires_clean_mem": [key], "dirties_mem": [key]}
        return {}

    return {}


def needs_approval(args: dict) -> bool:
    filepath = args.get("filepath")
    if filepath is not None:
        from src.tools._approval import needs_path_approval

        return needs_path_approval(filepath)
    return False



# ---------------------------------------------------------------------------
# Read-only action implementations — return str
# ---------------------------------------------------------------------------


def _do_read_lines(args: dict, value: str, label: str) -> str:
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    number_lines = bool(args.get("number_lines"))
    delimiter = args.get("delimiter")

    if start_line is not None and start_line < 1:
        return "Error: start_line must be >= 1"
    if end_line is not None and end_line < 1:
        return "Error: end_line must be >= 1"
    if start_line is not None and end_line is not None and end_line < start_line:
        return "Error: end_line must be >= start_line"

    contents = _read_lines_range(value, start_line, end_line)
    if number_lines:
        effective_start = start_line if start_line is not None else 1
        return add_line_numbers(
            contents, start_line=effective_start, delimiter=delimiter
        )
    return contents


def _read_lines_range(text: str, start_line: int | None, end_line: int | None) -> str:
    if start_line is None and end_line is None:
        return text
    effective_start = start_line if start_line is not None else 1
    selected: list[str] = []
    for lineno, line in enumerate(StringIO(text), start=1):
        if lineno < effective_start:
            continue
        if end_line is not None and lineno > end_line:
            break
        selected.append(line)
    return "".join(selected)


def _do_search_by_regex(args: dict, value: str, label: str) -> str:
    pattern = args.get("pattern")
    if not pattern:
        return "Error: 'pattern' is required for action 'search_by_regex'."
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}"

    lines = value.split("\n")
    content_lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    if content_lines and content_lines[-1] == "" and value.endswith("\n"):
        content_lines = content_lines[:-1]

    total = len(content_lines)
    if total == 0:
        return f"{label!r} is empty -- no matches."

    width = len(str(total))

    matches: list[str] = []
    for i, line in enumerate(content_lines, start=1):
        if compiled.search(line):
            matches.append(f"{str(i).rjust(width)} | {line}")

    if not matches:
        return f"No matches found in {label!r}."
    return f"{len(matches)} match(es) in {label!r}:\n" + "\n".join(matches)


def _do_count_lines(args: dict, value: str, label: str) -> str:
    return str(_count_lines(value))


def _do_check_eol(args: dict, value: str, label: str) -> str:
    return check_eol(value)


def _do_check_indentation(args: dict, value: str, label: str) -> str:
    return check_indentation(value)


# ---------------------------------------------------------------------------
# Write action implementations — return (message, new_value)
# ---------------------------------------------------------------------------


def _do_normalize_eol(args: dict, value: str, label: str) -> tuple[str, str]:
    eol = args.get("eol")
    if not eol:
        return "Error: 'eol' is required for action 'normalize_eol'.", value
    result = normalize_eol(value, eol)
    return f"Line endings normalized to {eol.upper()} for {label!r}.\n\n{_make_diff(value, result)}", result


def _do_convert_indentation(args: dict, value: str, label: str) -> tuple[str, str]:
    to = args.get("to")
    if not to:
        return "Error: 'to' is required for action 'convert_indentation'.", value
    spaces_per_tab = int(args.get("spaces_per_tab", DEFAULT_SPACES_PER_TAB))
    result = convert_indentation(value, to, spaces_per_tab)
    return f"Indentation converted to {to} (spaces_per_tab={spaces_per_tab}) for {label!r}.\n\n{_make_diff(value, result)}", result


def _do_apply_patch(args: dict, value: str, label: str) -> tuple[str, str]:
    edits = args.get("edits")
    disable_auto_eol = bool(args.get("disable_auto_eol", False))
    trailing_newline = args.get("trailing_newline")  # bool | None

    if not edits:
        return "Error: 'edits' is required for action 'apply_patch'.", value
    if not isinstance(edits, list) or not all(isinstance(e, dict) for e in edits):
        return "Error: 'edits' must be an array of objects.", value

    try:
        result = _apply_edits(
            value,
            edits,
            auto_eol=not disable_auto_eol,
            trailing_newline=trailing_newline,
        )
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}", value
    except Exception as exc:
        return f"Error applying patch: {exc}", value

    original_lines = _count_lines(value)
    new_lines = _count_lines(result)
    delta = new_lines - original_lines
    sign = "+" if delta >= 0 else ""
    summary = f"Patch applied to {label!r}. Lines: {original_lines} -> {new_lines} ({sign}{delta})."
    return f"{summary}\n\n{_make_diff(value, result)}", result


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

_READ_ONLY_ACTIONS = {
    "read_lines": _do_read_lines,
    "search_by_regex": _do_search_by_regex,
    "count_lines": _do_count_lines,
    "check_eol": _do_check_eol,
    "check_indentation": _do_check_indentation,
}

_WRITE_ACTIONS = {
    "normalize_eol": _do_normalize_eol,
    "convert_indentation": _do_convert_indentation,
    "apply_patch": _do_apply_patch,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    key = args.get("key")
    filepath = args.get("filepath")
    action = args.get("action")

    if key and filepath:
        return "Error: provide exactly one of 'key' or 'filepath', not both."
    if not key and not filepath:
        return "Error: one of 'key' or 'filepath' is required."

    # Load content and set label for display messages.
    if filepath:
        label = filepath
        try:
            with open(filepath, "r", encoding="utf-8", newline="") as fh:
                value = fh.read()
        except FileNotFoundError:
            return f"Error: file not found: {filepath}"
        except OSError as e:
            return f"Error reading file: {e}"
    else:
        label = key
        memory = ensure_session_memory(session_data)
        value = memory.get(key)
        if not isinstance(value, str):
            return f"Error: key {key!r} does not hold a text value."

    if action in _READ_ONLY_ACTIONS:
        return _READ_ONLY_ACTIONS[action](args, value, label)

    if action in _WRITE_ACTIONS:
        message, new_value = _WRITE_ACTIONS[action](args, value, label)
        if not message.startswith("Error"):
            if filepath:
                try:
                    with open(filepath, "w", encoding="utf-8", newline="") as fh:
                        fh.write(new_value)
                except OSError as e:
                    return f"Error writing file: {e}"
            else:
                memory[key] = new_value
        return message

    return f"Error: unknown action {action!r}."
