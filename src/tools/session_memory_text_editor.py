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
    "insert_chars":        ("PARAMS_ONLY", 0),
    "replace_chars":       ("PARAMS_ONLY", 0),
    "delete_chars":        ("PARAMS_ONLY", 0),
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
            "\n\n"
            "LINE ENDING RULES:\n"
            "Only LF (\\n) and CRLF (\\r\\n) are recognised as line terminators. "
            "Bare \\r is treated as a regular character (e.g. terminal progress-bar output) "
            "and is never split on, removed, or converted by line operations. "
            "Line-mutating actions (insert_lines, replace_lines, delete_lines, apply_patch) "
            "re-encode the result to match the existing EOL style of the value "
            "(CRLF if any CRLF present, else LF); set disable_auto_eol=true to suppress. "
            "Char actions perform raw character-level edits with no EOL conversion. "
            "\n\n"
            "TRAILING NEWLINE RULES:\n"
            "insert_lines and replace_lines do NOT add or remove a trailing newline -- "
            "whatever line endings are present in 'text' are used verbatim (after EOL "
            "style normalisation). Set ensure_newline=true to add one if absent. "
            "apply_patch always respects the patch's own trailing-newline specification "
            "(the '\\ No newline at end of file' marker), independent of disable_auto_eol. "
            "\n\n"
            "Actions: read_lines, read_char_range, insert_lines, replace_lines, delete_lines, "
            "insert_chars, replace_chars, delete_chars, "
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
                        "insert_chars", "replace_chars", "delete_chars",
                        "count_chars", "count_lines",
                        "check_eol", "normalize_eol",
                        "check_indentation", "convert_indentation",
                        "apply_patch",
                    ],
                    "description": (
                        "The operation to perform:\n"
                        "  read_lines          -- read all or a line range (1-based inclusive).\n"
                        "  read_char_range     -- read all or a char range (0-based, end exclusive).\n"
                        "  insert_lines        -- insert text before a 1-based line number; "
                        "auto-matches EOL style; trailing newline not added unless ensure_newline=true.\n"
                        "  replace_lines       -- replace a 1-based inclusive line range with new text; "
                        "auto-matches EOL style; trailing newline not added unless ensure_newline=true.\n"
                        "  delete_lines        -- delete a 1-based inclusive line range; auto-matches EOL style.\n"
                        "  insert_chars        -- insert text before a 0-based char position; no EOL conversion.\n"
                        "  replace_chars       -- replace a 0-based char range (end exclusive) with new text; no EOL conversion.\n"
                        "  delete_chars        -- delete a 0-based char range (end exclusive); no EOL conversion.\n"
                        "  count_chars         -- count total characters.\n"
                        "  count_lines         -- count total lines.\n"
                        "  check_eol           -- report line-ending style statistics.\n"
                        "  normalize_eol       -- normalize all line endings to a single style.\n"
                        "  check_indentation   -- report indentation style statistics.\n"
                        "  convert_indentation -- convert leading-whitespace indentation style.\n"
                        "  apply_patch         -- apply a unified diff patch; auto-matches EOL style; "
                        "always respects the patch's trailing-newline specification."
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
                    "description": (
                        "0-based character index. "
                        "Used by: read_char_range (start, inclusive), "
                        "insert_chars (insert before this position; 0 = prepend, beyond end = append), "
                        "replace_chars (start, inclusive), delete_chars (start, inclusive)."
                    ),
                },
                "end_char": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "0-based character index (exclusive). "
                        "Used by: read_char_range, replace_chars, delete_chars."
                    ),
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
                        "The text content. "
                        "For line operations (insert_lines, replace_lines): inserted verbatim after "
                        "EOL style normalisation (auto-match to existing value unless disable_auto_eol=true). "
                        "A trailing newline is NOT added automatically -- include one if you want the "
                        "inserted block to end as a complete line; omit it to fuse the last inserted "
                        "fragment with whatever follows. Set ensure_newline=true to add one if absent. "
                        "For char operations (insert_chars, replace_chars): written verbatim with no EOL conversion. "
                        "Used by: insert_lines, replace_lines, insert_chars, replace_chars."
                    ),
                },
                "disable_auto_eol": {
                    "type": "boolean",
                    "description": (
                        "If true, skip automatic EOL style normalisation and write the result verbatim. "
                        "By default (false), line-mutating operations (insert_lines, replace_lines, "
                        "delete_lines, apply_patch) re-encode the result to match the existing "
                        "EOL style of the value: CRLF if any CRLF is present, else LF. "
                        "This flag does NOT affect trailing-newline behaviour: "
                        "apply_patch always derives the trailing newline from the patch spec; "
                        "insert_lines/replace_lines always use whatever is in 'text' (see ensure_newline)."
                    ),
                },
                "ensure_newline": {
                    "type": "boolean",
                    "description": (
                        "If true, append a newline to 'text' before inserting if it does not already "
                        "end with one. This ensures the inserted block ends as a complete line. "
                        "Default false. The appended newline is subject to EOL style normalisation "
                        "(i.e. becomes \\r\\n for CRLF files unless disable_auto_eol=true). "
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


# ---------------------------------------------------------------------------
# Line-splitting helpers
# ---------------------------------------------------------------------------

def _split_lines_keepends(text: str) -> List[str]:
    """Split *text* into lines with their terminators preserved.

    Only \\n is treated as a line boundary.  Bare \\r is a regular character
    and is never used as a split point.  \\r\\n pairs are kept intact because
    the \\r stays attached to its line when we split on \\n.

    This is the correct replacement for str.splitlines(keepends=True) for
    file-content operations: it matches the behaviour of GNU diff/patch,
    grep, and the unidiff library (which uses StringIO iteration, also
    \\n-only).
    """
    if not text:
        return []
    parts = text.split('\n')
    result: List[str] = []
    # All parts except the last get their \n restored.
    for part in parts[:-1]:
        result.append(part + '\n')
    # The last part is non-empty only when there is no trailing \n.
    if parts[-1]:
        result.append(parts[-1])
    return result


def _split_lines_preserve(text: str) -> Tuple[List[str], bool]:
    """Split *text* into content lines (without terminators).

    Only \\n is treated as a line boundary (bare \\r is a character).
    For CRLF lines the trailing \\r (part of the \\r\\n terminator) is
    stripped from each line's content.

    Returns (lines, had_trailing_newline).
    """
    if text == "":
        return [], False
    had_trailing_newline = text.endswith("\n")
    parts = text.split('\n')
    # Remove the empty string produced by a trailing \n.
    if parts and parts[-1] == '':
        parts = parts[:-1]
    # Strip one trailing \r per part: this removes the \r from \r\n terminators.
    # A bare \r in the middle of a line is preserved because split('\n') does
    # not split on it, so it can only appear at the end of a part if it was
    # part of a \r\n pair.
    lines = [p[:-1] if p.endswith('\r') else p for p in parts]
    return lines, had_trailing_newline


# ---------------------------------------------------------------------------
# EOL style helpers
# ---------------------------------------------------------------------------

def _detect_newline_style(text: str) -> str:
    """Return \\r\\n if the text contains any CRLF, else \\n."""
    return "\r\n" if "\r\n" in text else "\n"


def _auto_match_eol(result: str, original: str) -> str:
    """Re-encode *result* line endings to match *original*'s EOL style.

    If *original* contains any CRLF, the result is normalised to CRLF.
    Otherwise it is normalised to LF-only.
    Bare \\r characters are not affected.
    """
    target = _detect_newline_style(original)
    # Collapse CRLF to LF first, then apply target.
    # Bare \r is untouched because we only replace the two-char \r\n sequence.
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
# patch helper
# ---------------------------------------------------------------------------

def _apply_patch(original_text: str, patch_text: str, auto_eol: bool = True) -> str:
    """Apply a unified diff to an in-memory string.

    EOL style of the result matches the original when auto_eol=True (default).
    Trailing-newline presence is always derived from the patch's own
    '\\ No newline at end of file' markers, regardless of auto_eol.
    Bare \\r is treated as a character throughout (not a line terminator).
    Small position fuzz (up to 3 lines) is applied when hunks don't match
    exactly at their stated position.
    """
    try:
        from unidiff import PatchSet
    except ImportError:
        raise RuntimeError(
            "The 'unidiff' package is required for apply_patch. "
            "Install it with: pip install unidiff"
        )

    newline = _detect_newline_style(original_text) if auto_eol else "\n"
    orig_lines, orig_had_final_nl = _split_lines_preserve(original_text)

    # Normalise the patch text to plain LF before handing to unidiff.
    # unidiff uses StringIO iteration (splits on \n only), so CRLF in the
    # patch would leave \r inside line.value.  Pre-normalising avoids this.
    patch_text_normalised = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    patchset = PatchSet(patch_text_normalised)

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

    # ------------------------------------------------------------------
    # Determine trailing newline from the patch's own specification.
    #
    # The patch format uses '\\ No newline at end of file' (line_type '\\')
    # after the last added/context line to signal that the new file should
    # NOT end with a newline.  We honour this regardless of auto_eol.
    #
    # Default: inherit from original.  Override only when the last hunk's
    # source coverage reaches the end of the original file (meaning the patch
    # explicitly controls what the new end-of-file looks like).
    # ------------------------------------------------------------------
    result_has_trailing_nl = orig_had_final_nl

    pfile_hunks = list(pfile)  # PatchedFile is a list; safe to re-iterate
    if pfile_hunks:
        last_hunk = pfile_hunks[-1]

        # source_start and source_length are 1-based / count of original lines.
        # last_src_line: last 1-based original line covered by this hunk.
        last_src_line = last_hunk.source_start + last_hunk.source_length - 1

        # Hunk reaches the end of the original file when:
        #   - last_src_line >= len(orig_lines)  (covers through last line), OR
        #   - original file is empty (any hunk defines the new content entirely)
        if len(orig_lines) == 0 or last_src_line >= len(orig_lines):
            hunk_lines = list(last_hunk)

            # Find the last line in the hunk that contributes to the result
            # (added '+' or context ' ').  Removed '-' and NO_NEWLINE '\\' lines
            # do not appear in the output.
            last_result_idx = -1
            for i, ln in enumerate(hunk_lines):
                if ln.line_type in ('+', ' '):
                    last_result_idx = i

            if last_result_idx == -1:
                # Every original line was removed and nothing added.
                result_has_trailing_nl = False
            else:
                # Check for a NO_NEWLINE marker immediately after the last result line.
                next_idx = last_result_idx + 1
                if (next_idx < len(hunk_lines) and
                        hunk_lines[next_idx].line_type == '\\'):
                    result_has_trailing_nl = False
                else:
                    result_has_trailing_nl = True

    result = newline.join(lines)
    if result_has_trailing_nl:
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
    # StringIO iteration splits on \n only -- consistent with our \n-only policy.
    for lineno, line in enumerate(StringIO(text), start=1):
        if lineno < effective_start:
            continue
        if end_line is not None and lineno > end_line:
            break
        selected.append(line)
    return "".join(selected)


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
    disable_auto_eol = bool(args.get("disable_auto_eol", False))
    ensure_newline = bool(args.get("ensure_newline", False))

    if before_line is None:
        return "Error: 'before_line' is required for action 'insert_lines'."
    if text is None:
        return "Error: 'text' is required for action 'insert_lines'."

    # Optionally ensure the inserted block ends with a newline.
    if ensure_newline and not text.endswith("\n"):
        text += "\n"

    # Split using \n-only splitting (bare \r is a character, not a boundary).
    existing_lines = _split_lines_keepends(value)
    insert_idx = min(before_line - 1, len(existing_lines))
    insert_idx = max(insert_idx, 0)
    inserted_lines = _split_lines_keepends(text)
    existing_lines[insert_idx:insert_idx] = inserted_lines
    result = "".join(existing_lines)

    if not disable_auto_eol:
        result = _auto_match_eol(result, value)

    memory[key] = result

    inserted_count = len(inserted_lines)
    return f"Inserted {inserted_count} line(s) before line {before_line} in {key!r}."


def _do_replace_lines(args: dict, key: str, value: str, memory: dict) -> str:
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    text = args.get("text")
    disable_auto_eol = bool(args.get("disable_auto_eol", False))
    ensure_newline = bool(args.get("ensure_newline", False))

    if start_line is None or end_line is None:
        return "Error: 'start_line' and 'end_line' are required for action 'replace_lines'."
    if text is None:
        return "Error: 'text' is required for action 'replace_lines'."
    if end_line < start_line:
        return "Error: end_line must be >= start_line."

    # Optionally ensure the replacement block ends with a newline.
    if ensure_newline and not text.endswith("\n"):
        text += "\n"

    lines = _split_lines_keepends(value)
    total = len(lines)

    if start_line > total:
        return f"Error: start_line {start_line} exceeds total line count {total}."

    clamped_end = min(end_line, total)
    replacement_lines = _split_lines_keepends(text)
    lines[start_line - 1:clamped_end] = replacement_lines
    result = "".join(lines)

    if not disable_auto_eol:
        result = _auto_match_eol(result, value)

    memory[key] = result

    removed = clamped_end - start_line + 1
    added = len(replacement_lines)
    return (
        f"Replaced lines {start_line}-{clamped_end} ({removed} line(s)) "
        f"with {added} line(s) in {key!r}."
    )


def _do_delete_lines(args: dict, key: str, value: str, memory: dict) -> str:
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    disable_auto_eol = bool(args.get("disable_auto_eol", False))

    if start_line is None or end_line is None:
        return "Error: 'start_line' and 'end_line' are required for action 'delete_lines'."
    if end_line < start_line:
        return "Error: end_line must be >= start_line."

    lines = _split_lines_keepends(value)
    total = len(lines)

    if start_line > total:
        return f"Error: start_line {start_line} exceeds total line count {total}."

    clamped_end = min(end_line, total)
    deleted_count = clamped_end - start_line + 1
    del lines[start_line - 1:clamped_end]
    result = "".join(lines)

    if not disable_auto_eol:
        result = _auto_match_eol(result, value)

    memory[key] = result

    return f"Deleted {deleted_count} line(s) ({start_line}-{clamped_end}) from {key!r}."


def _do_insert_chars(args: dict, key: str, value: str, memory: dict) -> str:
    start_char = args.get("start_char")
    text = args.get("text")

    if start_char is None:
        return "Error: 'start_char' is required for action 'insert_chars'."
    if text is None:
        return "Error: 'text' is required for action 'insert_chars'."

    idx = max(0, min(start_char, len(value)))
    memory[key] = value[:idx] + text + value[idx:]
    return f"Inserted {len(text)} character(s) at position {start_char} in {key!r}."


def _do_replace_chars(args: dict, key: str, value: str, memory: dict) -> str:
    start_char = args.get("start_char")
    end_char = args.get("end_char")
    text = args.get("text")

    if start_char is None or end_char is None:
        return "Error: 'start_char' and 'end_char' are required for action 'replace_chars'."
    if text is None:
        return "Error: 'text' is required for action 'replace_chars'."
    if end_char < start_char:
        return "Error: end_char must be >= start_char."

    removed = value[start_char:end_char]
    memory[key] = value[:start_char] + text + value[end_char:]
    return (
        f"Replaced {len(removed)} character(s) ({start_char}-{end_char}) "
        f"with {len(text)} character(s) in {key!r}."
    )


def _do_delete_chars(args: dict, key: str, value: str, memory: dict) -> str:
    start_char = args.get("start_char")
    end_char = args.get("end_char")

    if start_char is None or end_char is None:
        return "Error: 'start_char' and 'end_char' are required for action 'delete_chars'."
    if end_char < start_char:
        return "Error: end_char must be >= start_char."

    deleted = value[start_char:end_char]
    memory[key] = value[:start_char] + value[end_char:]
    return f"Deleted {len(deleted)} character(s) ({start_char}-{end_char}) from {key!r}."


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
    disable_auto_eol = bool(args.get("disable_auto_eol", False))

    if not patch:
        return "Error: 'patch' is required for action 'apply_patch'."

    try:
        result = _apply_patch(value, patch, auto_eol=not disable_auto_eol)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error applying patch: {exc}"

    memory[key] = result

    # Use _count_lines (LF-only counting) rather than str.splitlines()
    # to avoid bare \r being counted as line boundaries.
    original_lines = _count_lines(value)
    new_lines = _count_lines(result)
    delta = new_lines - original_lines
    sign = "+" if delta >= 0 else ""
    return (
        f"Patch applied to {key!r}. "
        f"Lines: {original_lines} -> {new_lines} ({sign}{delta})."
    )


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

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
    "insert_chars": _do_insert_chars,
    "replace_chars": _do_replace_chars,
    "delete_chars": _do_delete_chars,
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
