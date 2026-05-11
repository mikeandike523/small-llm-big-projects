from __future__ import annotations

import difflib
import re
from io import StringIO
from pathlib import Path
from typing import List, Tuple

from src.tools._eol import EOL_CHOICES, check_eol, normalize_eol
from src.tools._indentation import (
    INDENT_TARGET_CHOICES,
    DEFAULT_SPACES_PER_TAB,
    check_indentation,
    convert_indentation,
)
from src.tools._memory import ensure_session_memory
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
                        "read_lines", "search_by_regex",
                        "count_lines",
                        "check_eol", "normalize_eol",
                        "check_indentation", "convert_indentation",
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

_READ_ONLY_ACTIONS_SET = {
    "read_lines", "search_by_regex",
    "count_lines", "check_eol", "check_indentation",
}
_WRITE_ACTIONS_SET = {
    "normalize_eol", "convert_indentation", "apply_patch",
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

    # read_lines: cleaning logic commented out — partial reads do not clean dirty state.
    # Only read_text_file (for files) or session_memory(action="get") (for mem) can clean.
    # The range-based cleaning below caused agent loops where a partial read was expected
    # to unblock subsequent writes, but then the write was blocked again on the next edit.
    #
    # if action == "read_lines":
    #     start = args.get("start_line")
    #     end = args.get("end_line")
    #     if start is not None and start != 1:
    #         return {}
    #     if end is None:
    #         if filepath:
    #             return {"cleans_files": [filepath]}
    #         if key:
    #             return {"cleans_mem": [key]}
    #         return {}
    #     # Explicit end -- verify against actual content length
    #     if filepath:
    #         try:
    #             content = Path(filepath).resolve().read_text(encoding="utf-8")
    #             total = 0 if content == "" else content.count("\n") + (0 if content.endswith("\n") else 1)
    #             if end >= total:
    #                 return {"cleans_files": [filepath]}
    #         except OSError:
    #             pass
    #     if key and session_data is not None:
    #         memory = session_data.get("memory") or {}
    #         content = memory.get(key)
    #         if isinstance(content, str):
    #             total = 0 if content == "" else content.count("\n") + (0 if content.endswith("\n") else 1)
    #             if end >= total:
    #                 return {"cleans_mem": [key]}
    #     return {}

    # search_by_regex, count_lines, check_eol, check_indentation:
    # these reveal metadata but not the full content — no clean signal
    return {}


def needs_approval(args: dict) -> bool:
    filepath = args.get("filepath")
    if filepath is not None:
        from src.tools._approval import needs_path_approval
        return needs_path_approval(filepath)
    return False


# ---------------------------------------------------------------------------
# Internal buffer key used in filepath mode
# ---------------------------------------------------------------------------

_FILE_BUF_KEY = "__filepath_buf__"


# ---------------------------------------------------------------------------
# Line-splitting helpers
# ---------------------------------------------------------------------------

def _split_lines_preserve(text: str) -> Tuple[List[str], bool]:
    """Split *text* into content lines (without terminators).

    Only \\n is treated as a line boundary (bare \\r is a character).
    Returns (lines, had_trailing_newline).
    """
    if text == "":
        return [], False
    had_trailing_newline = text.endswith("\n")
    parts = text.split('\n')
    if parts and parts[-1] == '':
        parts = parts[:-1]
    lines = [p[:-1] if p.endswith('\r') else p for p in parts]
    return lines, had_trailing_newline


# ---------------------------------------------------------------------------
# EOL style helpers
# ---------------------------------------------------------------------------

def _detect_newline_style(text: str) -> str:
    """Return \\r\\n if the text contains any CRLF, else \\n."""
    return "\r\n" if "\r\n" in text else "\n"


def _auto_match_eol(result: str, original: str) -> str:
    """Re-encode *result* line endings to match *original*'s EOL style."""
    target = _detect_newline_style(original)
    normalised = result.replace("\r\n", "\n")
    if target == "\r\n":
        return normalised.replace("\n", "\r\n")
    return normalised


# ---------------------------------------------------------------------------
# Line counting
# ---------------------------------------------------------------------------

def _count_lines(text: str) -> int:
    """Count logical lines, treating \\n as the sole line boundary."""
    if text == "":
        return 0
    newline_count = text.count("\n")
    if text.endswith("\n"):
        return newline_count
    return newline_count + 1


# ---------------------------------------------------------------------------
# diff helper
# ---------------------------------------------------------------------------

def _make_diff(before: str, after: str) -> str:
    """Return a unified diff string comparing before to after (no trailing newline)."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    diff_lines = list(difflib.unified_diff(before_lines, after_lines, fromfile="before", tofile="after", lineterm=""))
    return "\n".join(diff_lines) if diff_lines else "(no visible changes)"


# ---------------------------------------------------------------------------
# simple edit helpers
# ---------------------------------------------------------------------------

def _parse_simple_edit(edit_text: str) -> tuple[list[str], list[str]]:
    """Parse a simple edit block into (before_lines, after_lines).

    '+' prefix  → add (after only)
    '-' prefix  → remove (before only)
    ' ' prefix  → context (before and after, prefix stripped)
    no prefix   → also context
    """
    before: list[str] = []
    after: list[str] = []
    for raw in edit_text.splitlines():
        if raw.startswith('+'):
            after.append(raw[1:])
        elif raw.startswith('-'):
            before.append(raw[1:])
        else:
            content = raw[1:] if raw.startswith(' ') else raw
            before.append(content)
            after.append(content)
    return before, after


def _apply_edits(
    original_text: str,
    edits: list[dict],
    auto_eol: bool = True,
    trailing_newline: bool | None = None,
) -> str:
    """Apply a list of simple edit objects to original_text.

    trailing_newline: None = preserve original, True = ensure, False = strip.
    """
    newline = _detect_newline_style(original_text) if auto_eol else "\n"
    lines, had_trailing_nl = _split_lines_preserve(original_text)

    for n, edit in enumerate(edits, start=1):
        edit_text = edit.get("text", "")
        position = edit.get("position")
        before, after = _parse_simple_edit(edit_text)

        if not before:
            # Pure insertion: no content to anchor on — require position.
            if position is None:
                raise ValueError(
                    f"Edit {n}: no context or removed lines to anchor on, and no 'position' given. "
                    "Either include at least one context line (space prefix) or removed line ('-'), "
                    "or set 'position' to a 1-based line number for pure insertions."
                )
            apply_at = min(max(position - 1, 0), len(lines))
            lines = lines[:apply_at] + after + lines[apply_at:]
        else:
            before_keys = [s.rstrip() for s in before]
            hits = [
                i for i in range(len(lines))
                if (i + len(before_keys) <= len(lines) and
                    [s.rstrip() for s in lines[i: i + len(before_keys)]] == before_keys)
            ]

            if not hits:
                raise ValueError(f"Edit {n}: context did not match anywhere in the target.")
            if len(hits) > 1:
                raise ValueError(
                    f"Edit {n}: context matches multiple locations "
                    f"({[h + 1 for h in hits]}); ambiguous, refusing to apply."
                )

            apply_at = hits[0]
            lines = lines[:apply_at] + after + lines[apply_at + len(before):]

    ends_with_nl = had_trailing_nl if trailing_newline is None else trailing_newline
    result = newline.join(lines)
    if ends_with_nl:
        result += newline
    return result


# ---------------------------------------------------------------------------
# action implementations
# ---------------------------------------------------------------------------

def _do_read_lines(args: dict, key: str, value: str) -> str:
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
        return add_line_numbers(contents, start_line=effective_start, delimiter=delimiter)
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


def _do_search_by_regex(args: dict, key: str, value: str) -> str:
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
        return f"{key!r} is empty -- no matches."

    width = len(str(total))
    _BOLD = "\033[1m"
    _RESET = "\033[0m"

    def _highlight(line: str) -> str:
        try:
            return re.sub(pattern, lambda m: f"{_BOLD}{m.group(0)}{_RESET}", line)
        except re.error:
            return line

    matches: list[str] = []
    for i, line in enumerate(content_lines, start=1):
        if compiled.search(line):
            matches.append(f"{str(i).rjust(width)} | {_highlight(line)}")

    if not matches:
        return f"No matches found in {key!r}."
    return f"{len(matches)} match(es) in {key!r}:\n" + "\n".join(matches)


def _do_count_lines(args: dict, key: str, value: str) -> str:
    return str(_count_lines(value))


def _do_check_eol(args: dict, key: str, value: str) -> str:
    return check_eol(value)


def _do_normalize_eol(args: dict, key: str, value: str, memory: dict) -> str:
    eol = args.get("eol")
    if not eol:
        return "Error: 'eol' is required for action 'normalize_eol'."
    result = normalize_eol(value, eol)
    memory[key] = result
    return f"Line endings normalized to {eol.upper()} for {key!r}.\n\n{_make_diff(value, result)}"


def _do_check_indentation(args: dict, key: str, value: str) -> str:
    return check_indentation(value)


def _do_convert_indentation(args: dict, key: str, value: str, memory: dict) -> str:
    to = args.get("to")
    if not to:
        return "Error: 'to' is required for action 'convert_indentation'."
    spaces_per_tab = int(args.get("spaces_per_tab", DEFAULT_SPACES_PER_TAB))
    result = convert_indentation(value, to, spaces_per_tab)
    memory[key] = result
    return f"Indentation converted to {to} (spaces_per_tab={spaces_per_tab}) for {key!r}.\n\n{_make_diff(value, result)}"


def _do_apply_patch(args: dict, key: str, value: str, memory: dict) -> str:
    edits = args.get("edits")
    disable_auto_eol = bool(args.get("disable_auto_eol", False))
    trailing_newline = args.get("trailing_newline")  # bool | None

    if not edits:
        return "Error: 'edits' is required for action 'apply_patch'."
    if not isinstance(edits, list) or not all(isinstance(e, dict) for e in edits):
        return "Error: 'edits' must be an array of objects."

    try:
        result = _apply_edits(
            value, edits,
            auto_eol=not disable_auto_eol,
            trailing_newline=trailing_newline,
        )
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error applying patch: {exc}"

    memory[key] = result

    original_lines = _count_lines(value)
    new_lines = _count_lines(result)
    delta = new_lines - original_lines
    sign = "+" if delta >= 0 else ""
    summary = f"Patch applied to {key!r}. Lines: {original_lines} -> {new_lines} ({sign}{delta})."
    return f"{summary}\n\n{_make_diff(value, result)}"


# ---------------------------------------------------------------------------
# dispatch tables
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
# execute helpers
# ---------------------------------------------------------------------------

def _execute_memory(action: str, args: dict, key: str, session_data: dict) -> str:
    memory = ensure_session_memory(session_data)
    value = memory.get(key)
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."
    if action in _READ_ONLY_ACTIONS:
        return _READ_ONLY_ACTIONS[action](args, key, value)
    elif action in _WRITE_ACTIONS:
        return _WRITE_ACTIONS[action](args, key, value, memory)
    else:
        return f"Error: unknown action {action!r}."


def _execute_filepath(action: str, args: dict, filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", newline="") as fh:
            content = fh.read()
    except FileNotFoundError:
        return f"Error: file not found: {filepath}"
    except OSError as e:
        return f"Error reading file: {e}"

    buf_key = _FILE_BUF_KEY
    buf = {buf_key: content}
    effective_args = dict(args)
    effective_args["key"] = buf_key

    if action in _READ_ONLY_ACTIONS:
        result = _READ_ONLY_ACTIONS[action](effective_args, buf_key, content)
    elif action in _WRITE_ACTIONS:
        result = _WRITE_ACTIONS[action](effective_args, buf_key, content, buf)
        if not result.startswith("Error"):
            new_content = buf.get(buf_key, content)
            try:
                with open(filepath, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new_content)
            except OSError as e:
                return f"Error writing file: {e}"
    else:
        return f"Error: unknown action {action!r}."

    return result.replace(repr(buf_key), repr(filepath))


# ---------------------------------------------------------------------------
# main entry point
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

    if filepath:
        return _execute_filepath(action, args, filepath)
    else:
        return _execute_memory(action, args, key, session_data)
