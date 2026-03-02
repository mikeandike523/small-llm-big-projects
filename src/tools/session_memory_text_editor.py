from __future__ import annotations

from io import StringIO
from typing import List, Optional, Tuple

from src.tools._eol import EOL_CHOICES, check_eol, normalize_eol
from src.tools._indentation import (
    INDENT_TARGET_CHOICES,
    DEFAULT_SPACES_PER_TAB,
    check_indentation,
    convert_indentation,
)
from src.tools._memory import ensure_session_memory
from src.utils.text.line_numbers import add_line_numbers

LEAVE_OUT = "KEEP"  # module-level fallback; per-action policy takes precedence

LEAVE_OUT_PER_ACTION = {
    "read_lines":          ("SHORT",       500),
    "read_char_range":     ("SHORT",       500),
    "insert_lines":        ("PARAMS_ONLY", 0),
    "replace_lines":       ("PARAMS_ONLY", 0),
    "delete_lines":        ("PARAMS_ONLY", 0),
    "count_chars":         ("OMIT",        0),
    "count_lines":         ("OMIT",        0),
    "check_eol":           ("KEEP",        0),
    "normalize_eol":       ("PARAMS_ONLY", 0),
    "check_indentation":   ("KEEP",        0),
    "convert_indentation": ("PARAMS_ONLY", 0),
    "apply_patch":         ("KEEP",        0),
}

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_text_editor",
        "description": (
            "Structural text-editor operations on session memory string values. "
            "Part of the in-memory text editor toolkit: "
            "read_text_file_to_session_memory -> edit -> write_text_file_from_session_memory. "
            "Actions: read_lines, read_char_range, insert_lines, replace_lines, delete_lines, "
            "count_chars, count_lines, check_eol, normalize_eol, "
            "check_indentation, convert_indentation, apply_patch."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "read_lines", "read_char_range",
                        "insert_lines", "replace_lines", "delete_lines",
                        "count_chars", "count_lines",
                        "check_eol", "normalize_eol",
                        "check_indentation", "convert_indentation",
                        "apply_patch",
                    ],
                    "description": (
                        "The operation to perform:\n"
                        "  read_lines          -- read all or a line range (1-based inclusive).\n"
                        "  read_char_range     -- read all or a char range (0-based, end exclusive).\n"
                        "  insert_lines        -- insert text before a 1-based line number.\n"
                        "  replace_lines       -- replace a 1-based inclusive line range with new text.\n"
                        "  delete_lines        -- delete a 1-based inclusive line range.\n"
                        "  count_chars         -- count total characters.\n"
                        "  count_lines         -- count total lines.\n"
                        "  check_eol           -- report line-ending style statistics.\n"
                        "  normalize_eol       -- normalize all line endings to a single style.\n"
                        "  check_indentation   -- report indentation style statistics.\n"
                        "  convert_indentation -- convert leading-whitespace indentation style.\n"
                        "  apply_patch         -- apply a unified diff patch."
                    ),
                },
                "key": {
                    "type": "string",
                    "description": "The session memory key. Must hold a text value. Required for all actions.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based line number. "
                        "Used by: read_lines (start, inclusive), replace_lines (start, inclusive), "
                        "delete_lines (start, inclusive)."
                    ),
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based line number (inclusive). "
                        "Used by: read_lines, replace_lines, delete_lines."
                    ),
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
                "start_char": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "0-based character index to start reading from (inclusive). Used by: read_char_range.",
                },
                "end_char": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "0-based character index to stop reading at (exclusive). Used by: read_char_range.",
                },
                "before_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based line number to insert before. "
                        "Use 1 to prepend; values beyond the last line append to end. "
                        "Used by: insert_lines."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The text content. Treated as complete lines where applicable; "
                        "a trailing newline is added automatically if absent. "
                        "Used by: insert_lines, replace_lines."
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
                "patch": {
                    "type": "string",
                    "description": (
                        "Standard unified diff text (e.g. output of `diff -u`). "
                        "Must start with --- / +++ header lines and contain one or more hunks. "
                        "Do NOT include 'begin patch', 'end patch', or any other wrapper -- "
                        "raw diff text only. Used by: apply_patch."
                    ),
                },
            },
            "required": ["action", "key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


# ---- helper utilities -------------------------------------------------------

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


def _count_lines(text: str) -> int:
    if text == "":
        return 0
    newline_count = text.count("\n")
    if text.endswith("\n"):
        return newline_count
    return newline_count + 1


def _detect_newline_style(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _split_lines_preserve(text: str) -> Tuple[List[str], bool]:
    if text == "":
        return [], False
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()
    return lines, had_trailing_newline


def _apply_patch(original_text: str, patch_text: str) -> str:
    """Apply a unified diff to an in-memory string with CRLF-awareness and small offset fuzz."""
    try:
        from unidiff import PatchSet
    except ImportError:
        raise RuntimeError(
            "The 'unidiff' package is required for apply_patch. "
            "Install it with: pip install unidiff"
        )

    newline = _detect_newline_style(original_text)
    orig_lines, orig_had_final_nl = _split_lines_preserve(original_text)

    patch_text_normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    patchset = PatchSet(patch_text_normalized)

    if len(patchset) == 0:
        raise ValueError("Patch contains no file entries.")
    if len(patchset) > 1:
        raise ValueError(
            f"Patch targets {len(patchset)} files; this tool applies patches to a single "
            "session memory value (one file) at a time."
        )

    pfile = patchset[0]
    lines = list(orig_lines)
    max_offset = 3

    for hunk in pfile:
        target_index_0 = max(hunk.source_start - 1, 0)

        expected_before: List[str] = [
            ln.value.rstrip("\n\r")
            for ln in hunk
            if ln.is_context or ln.is_removed
        ]
        expected_after: List[str] = [
            ln.value.rstrip("\n\r")
            for ln in hunk
            if ln.is_context or ln.is_added
        ]

        def matches_at(idx: int) -> bool:
            if idx < 0:
                return False
            if idx + len(expected_before) > len(lines):
                return False
            return lines[idx: idx + len(expected_before)] == expected_before

        apply_at: Optional[int] = None

        if matches_at(target_index_0):
            apply_at = target_index_0
        else:
            lo = max(0, target_index_0 - max_offset)
            hi = min(len(lines), target_index_0 + max_offset + 1)
            hits = [i for i in range(lo, hi) if matches_at(i)]

            if len(hits) == 1:
                apply_at = hits[0]
            elif len(hits) == 0:
                raise ValueError(
                    f"Hunk @@ line {hunk.source_start} did not match anywhere within "
                    f"+/-{max_offset} lines of the stated position."
                )
            else:
                raise ValueError(
                    f"Hunk @@ line {hunk.source_start} matches multiple locations "
                    f"({[h + 1 for h in hits]}); ambiguous, refusing to apply."
                )

        lines = (
            lines[:apply_at]
            + expected_after
            + lines[apply_at + len(expected_before):]
        )

    result = newline.join(lines)
    if orig_had_final_nl:
        result += newline
    return result


# ---- action implementations --------------------------------------------------

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


def _do_read_char_range(args: dict, key: str, value: str) -> str:
    start_char = args.get("start_char")
    end_char = args.get("end_char")

    if start_char is not None and start_char < 0:
        return "Error: start_char must be >= 0"
    if end_char is not None and end_char < 0:
        return "Error: end_char must be >= 0"
    if start_char is not None and end_char is not None and end_char < start_char:
        return "Error: end_char must be >= start_char"

    return value[start_char:end_char]


def _do_insert_lines(args: dict, key: str, value: str, memory: dict) -> str:
    before_line = args.get("before_line")
    text = args.get("text")
    if before_line is None:
        return "Error: 'before_line' is required for action 'insert_lines'."
    if text is None:
        return "Error: 'text' is required for action 'insert_lines'."

    if not text.endswith("\n"):
        text += "\n"

    lines = value.splitlines(keepends=True)
    insert_idx = min(before_line - 1, len(lines))
    insert_idx = max(insert_idx, 0)

    new_lines = value.splitlines(keepends=True)
    new_lines[insert_idx:insert_idx] = text.splitlines(keepends=True)
    memory[key] = "".join(new_lines)

    inserted_count = len(text.splitlines())
    return f"Inserted {inserted_count} line(s) before line {before_line} in {key!r}."


def _do_replace_lines(args: dict, key: str, value: str, memory: dict) -> str:
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    text = args.get("text")
    if start_line is None or end_line is None:
        return "Error: 'start_line' and 'end_line' are required for action 'replace_lines'."
    if text is None:
        return "Error: 'text' is required for action 'replace_lines'."

    if end_line < start_line:
        return "Error: end_line must be >= start_line."

    if not text.endswith("\n"):
        text += "\n"

    lines = value.splitlines(keepends=True)
    total = len(lines)

    if start_line > total:
        return f"Error: start_line {start_line} exceeds total line count {total}."

    clamped_end = min(end_line, total)
    replacement_lines = text.splitlines(keepends=True)
    lines[start_line - 1:clamped_end] = replacement_lines
    memory[key] = "".join(lines)

    removed = clamped_end - start_line + 1
    added = len(replacement_lines)
    return (
        f"Replaced lines {start_line}-{clamped_end} ({removed} line(s)) "
        f"with {added} line(s) in {key!r}."
    )


def _do_delete_lines(args: dict, key: str, value: str, memory: dict) -> str:
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if start_line is None or end_line is None:
        return "Error: 'start_line' and 'end_line' are required for action 'delete_lines'."

    if end_line < start_line:
        return "Error: end_line must be >= start_line."

    lines = value.splitlines(keepends=True)
    total = len(lines)

    if start_line > total:
        return f"Error: start_line {start_line} exceeds total line count {total}."

    clamped_end = min(end_line, total)
    deleted_count = clamped_end - start_line + 1
    del lines[start_line - 1:clamped_end]
    memory[key] = "".join(lines)

    return f"Deleted {deleted_count} line(s) ({start_line}-{clamped_end}) from {key!r}."


def _do_count_chars(args: dict, key: str, value: str) -> str:
    return str(len(value))


def _do_count_lines(args: dict, key: str, value: str) -> str:
    return str(_count_lines(value))


def _do_check_eol(args: dict, key: str, value: str) -> str:
    return check_eol(value)


def _do_normalize_eol(args: dict, key: str, value: str, memory: dict) -> str:
    eol = args.get("eol")
    if not eol:
        return "Error: 'eol' is required for action 'normalize_eol'."
    memory[key] = normalize_eol(value, eol)
    return f"Line endings normalized to {eol.upper()} for session memory key {key!r}."


def _do_check_indentation(args: dict, key: str, value: str) -> str:
    return check_indentation(value)


def _do_convert_indentation(args: dict, key: str, value: str, memory: dict) -> str:
    to = args.get("to")
    if not to:
        return "Error: 'to' is required for action 'convert_indentation'."
    spaces_per_tab = int(args.get("spaces_per_tab", DEFAULT_SPACES_PER_TAB))
    memory[key] = convert_indentation(value, to, spaces_per_tab)
    return f"Indentation converted to {to} (spaces_per_tab={spaces_per_tab}) for session memory key {key!r}."


def _do_apply_patch(args: dict, key: str, value: str, memory: dict) -> str:
    patch = args.get("patch")
    if not patch:
        return "Error: 'patch' is required for action 'apply_patch'."

    try:
        result = _apply_patch(value, patch)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error applying patch: {exc}"

    memory[key] = result

    original_lines = len(value.splitlines())
    new_lines = len(result.splitlines())
    delta = new_lines - original_lines
    sign = "+" if delta >= 0 else ""
    return (
        f"Patch applied to {key!r}. "
        f"Lines: {original_lines} -> {new_lines} ({sign}{delta})."
    )


# ---- dispatch ---------------------------------------------------------------

# Actions that need read-only access to value (no memory write)
_READ_ONLY_ACTIONS = {
    "read_lines": _do_read_lines,
    "read_char_range": _do_read_char_range,
    "count_chars": _do_count_chars,
    "count_lines": _do_count_lines,
    "check_eol": _do_check_eol,
    "check_indentation": _do_check_indentation,
}

# Actions that mutate memory (receive memory dict as well)
_WRITE_ACTIONS = {
    "insert_lines": _do_insert_lines,
    "replace_lines": _do_replace_lines,
    "delete_lines": _do_delete_lines,
    "normalize_eol": _do_normalize_eol,
    "convert_indentation": _do_convert_indentation,
    "apply_patch": _do_apply_patch,
}


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = ensure_session_memory(session_data)
    action = args.get("action")
    key = args.get("key")

    if not key:
        return "Error: 'key' is required."

    value = memory.get(key)
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    if action in _READ_ONLY_ACTIONS:
        return _READ_ONLY_ACTIONS[action](args, key, value)
    elif action in _WRITE_ACTIONS:
        return _WRITE_ACTIONS[action](args, key, value, memory)
    else:
        return f"Error: unknown action {action!r}."
