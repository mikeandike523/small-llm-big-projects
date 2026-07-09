"""Action implementations for the text_editor tool.

Each read-only action returns a str; each write action returns
(message, new_value).  Kept separate from text_editor.py to keep both files
under the project's 500-line limit.  The dispatch tables at the bottom are the
single source of truth for which actions exist.
"""

from __future__ import annotations

import re
from io import StringIO

from src.tools._eol import check_eol, normalize_eol
from src.tools._indentation import (
    DEFAULT_SPACES_PER_TAB,
    check_indentation,
    convert_indentation,
)
from src.tools._text_editor_utils import (
    LineGroup,
    ParsedHunk,
    _apply_edits,
    _count_lines,
    _detect_newline_style,
    _make_diff,
    _parse_patch_file,
    _split_lines_preserve,
)
from src.utils.text.line_numbers import add_line_numbers


# ---------------------------------------------------------------------------
# Line reconstruction (used by insert/delete/append/prepend line actions)
# ---------------------------------------------------------------------------


def _reconstruct(lines: list[str], newline: str, trailing_nl: bool) -> str:
    """Join *lines* with *newline*, adding a trailing newline when requested."""
    result = newline.join(lines)
    if trailing_nl and lines:
        result += newline
    return result


# ---------------------------------------------------------------------------
# search_replace — AIDER-style SEARCH/REPLACE blocks
# ---------------------------------------------------------------------------

# Lenient markers: models sometimes vary the fence-character count or omit the
# SEARCH/REPLACE words.  We only require the recognizable fence shape.
#
# The canonical AIDER fence is 7 characters ("<<<<<<< SEARCH" / "=======" /
# ">>>>>>> REPLACE").  AIDER's own parser accepts a range of 5-9 ({5,9}); we
# adopt the same minimum of 5 but leave the upper bound open, so a rare
# extra-character hallucination (8, 9, 10, ... in a row) still parses instead
# of failing the whole edit.
_SR_START_RE = re.compile(r"^<{5,}\s*(?:SEARCH)?\s*$")
_SR_DIVIDER_RE = re.compile(r"^={5,}\s*$")
_SR_END_RE = re.compile(r"^>{5,}\s*(?:REPLACE)?\s*$")


def _parse_search_replace(text: str) -> list[tuple[list[str], list[str]]]:
    """Parse AIDER-style SEARCH/REPLACE blocks into (search, replace) line lists.

    Format (fence-character counts are lenient; the SEARCH/REPLACE words are
    optional)::

        <<<<<<< SEARCH
        old line(s)
        =======
        new line(s)
        >>>>>>> REPLACE

    Multiple blocks may be concatenated in one input.  Raises ValueError on a
    malformed block (missing divider or terminator, or a marker appearing in
    the wrong state).  Search/replace line lists exclude terminators.
    """
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[tuple[list[str], list[str]]] = []
    state = "outside"  # outside | search | replace
    search: list[str] = []
    replace: list[str] = []

    for line in raw:
        if state == "outside":
            if _SR_START_RE.match(line):
                state, search, replace = "search", [], []
            # lines outside a block (blank lines, stray prose) are ignored
        elif state == "search":
            if _SR_DIVIDER_RE.match(line):
                state = "replace"
            elif _SR_START_RE.match(line) or _SR_END_RE.match(line):
                raise ValueError(
                    "malformed SEARCH/REPLACE block: expected a '=======' divider "
                    "before the next marker."
                )
            else:
                search.append(line)
        else:  # replace
            if _SR_END_RE.match(line):
                blocks.append((search, replace))
                state = "outside"
            elif _SR_START_RE.match(line) or _SR_DIVIDER_RE.match(line):
                raise ValueError(
                    "malformed SEARCH/REPLACE block: expected a '>>>>>>> REPLACE' "
                    "terminator before the next marker."
                )
            else:
                replace.append(line)

    if state != "outside":
        raise ValueError(
            "unterminated SEARCH/REPLACE block: expected a '>>>>>>> REPLACE' "
            "terminator (and, before it, a '=======' divider)."
        )

    return blocks


def apply_search_replace(original_text: str, text: str) -> str:
    """Apply AIDER-style SEARCH/REPLACE blocks to *original_text*.

    Each block's SEARCH lines are located with the same fuzzy, single-location,
    line-count-preserving matching used by apply_patch (there is no hunk header
    to parse — the SEARCH side is the match target and the REPLACE side is the
    replacement).  A block whose SEARCH matches zero or more than one location
    fails the whole operation with a descriptive error; no changes are applied.
    """
    blocks = _parse_search_replace(text)
    if not blocks:
        raise ValueError(
            "no SEARCH/REPLACE blocks found; expected '<<<<<<< SEARCH', "
            "'=======', and '>>>>>>> REPLACE' markers."
        )

    hunks: list[ParsedHunk] = []
    for search, replace in blocks:
        if not search:
            raise ValueError(
                "a SEARCH block is empty; search_replace needs text to locate. "
                "Use insert_lines / append_lines / prepend_lines to add content."
            )
        tagged = [("-", s) for s in search] + [("+", r) for r in replace]
        hunks.append(ParsedHunk(start=None, group=LineGroup(tagged=tagged)))

    return _apply_edits(original_text, hunks, unit="Block")

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
    patch = args.get("patch")
    if not patch:
        return "Error: 'patch' is required for action 'apply_patch'.", value
    if not isinstance(patch, str):
        return "Error: 'patch' must be a string.", value

    try:
        hunks = _parse_patch_file(patch)
    except Exception as exc:
        return f"Error parsing patch: {exc}", value

    if not hunks:
        return "Error: no hunks found in patch.", value

    try:
        result = _apply_edits(value, hunks)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}", value
    except Exception as exc:
        return f"Error applying patch: {exc}", value

    n = len(hunks)
    summary = f"Success: ({n}) {'hunk' if n == 1 else 'hunks'} applied to {label!r}."
    return f"{summary}\n\n{_make_diff(value, result)}", result


def _do_search_replace(args: dict, value: str, label: str) -> tuple[str, str]:
    patch = args.get("patch")
    if not patch:
        return (
            "Error: 'patch' is required for action 'search_replace' "
            "(AIDER-style '<<<<<<< SEARCH / ======= / >>>>>>> REPLACE' blocks).",
            value,
        )
    if not isinstance(patch, str):
        return "Error: 'patch' must be a string.", value

    try:
        result = apply_search_replace(value, patch)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}", value
    except Exception as exc:
        return f"Error applying search_replace: {exc}", value

    return f"Success: search/replace applied to {label!r}.\n\n{_make_diff(value, result)}", result


def _do_regex_replace(args: dict, value: str, label: str) -> tuple[str, str]:
    pattern = args.get("pattern")
    if not pattern:
        return "Error: 'pattern' is required for action 'regex_replace'.", value
    replacement = args.get("replacement")
    if replacement is None:
        return "Error: 'replacement' is required for action 'regex_replace'.", value
    if not isinstance(replacement, str):
        return "Error: 'replacement' must be a string.", value

    count = args.get("count", 0)
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "Error: 'count' must be an integer (0 = replace all).", value
    if count < 0:
        return "Error: 'count' must be >= 0 (0 = replace all).", value

    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}", value

    newline = _detect_newline_style(value)
    work = value.replace("\r\n", "\n")
    try:
        new_work, n = compiled.subn(replacement, work, count=count)
    except re.error as e:
        return f"Error: invalid replacement template: {e}", value

    if n == 0:
        return "Error: pattern matched nothing; no changes made.", value

    result = new_work.replace("\n", newline) if newline == "\r\n" else new_work
    plural = "replacement" if n == 1 else "replacements"
    return f"Success: {n} {plural} applied to {label!r}.\n\n{_make_diff(value, result)}", result


def _do_insert_lines(args: dict, value: str, label: str) -> tuple[str, str]:
    start_line = args.get("start_line")
    content = args.get("content")
    if start_line is None:
        return (
            "Error: 'start_line' is required for action 'insert_lines' "
            "(1-based; content is inserted before this line).",
            value,
        )
    if not isinstance(start_line, int) or start_line < 1:
        return "Error: 'start_line' must be an integer >= 1.", value
    if content is None:
        return "Error: 'content' is required for action 'insert_lines'.", value
    if not isinstance(content, str):
        return "Error: 'content' must be a string.", value

    orig_lines, orig_trailing = _split_lines_preserve(value)
    new_lines, content_trailing = _split_lines_preserve(content)
    if not new_lines:
        return "Error: 'content' is empty; nothing to insert.", value
    if start_line > len(orig_lines) + 1:
        return (
            f"Error: start_line {start_line} is beyond the end of the content "
            f"({len(orig_lines)} lines); use append_lines to add at the end.",
            value,
        )

    idx = start_line - 1
    result_lines = orig_lines[:idx] + new_lines + orig_lines[idx:]
    newline = _detect_newline_style(value)
    at_end = idx >= len(orig_lines)
    trailing = content_trailing if (at_end or not orig_lines) else orig_trailing
    result = _reconstruct(result_lines, newline, trailing)
    return (
        f"Success: inserted {len(new_lines)} line(s) at line {start_line} of {label!r}."
        f"\n\n{_make_diff(value, result)}",
        result,
    )


def _do_delete_lines(args: dict, value: str, label: str) -> tuple[str, str]:
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if start_line is None:
        return "Error: 'start_line' is required for action 'delete_lines'.", value
    if not isinstance(start_line, int) or start_line < 1:
        return "Error: 'start_line' must be an integer >= 1.", value
    if end_line is None:
        end_line = start_line
    if not isinstance(end_line, int) or end_line < 1:
        return "Error: 'end_line' must be an integer >= 1.", value
    if end_line < start_line:
        return "Error: end_line must be >= start_line.", value

    orig_lines, orig_trailing = _split_lines_preserve(value)
    total = len(orig_lines)
    if total == 0:
        return "Error: content is empty; nothing to delete.", value
    if start_line > total:
        return (
            f"Error: start_line {start_line} is beyond the end of the content "
            f"({total} lines).",
            value,
        )

    end = min(end_line, total)
    result_lines = orig_lines[: start_line - 1] + orig_lines[end:]
    newline = _detect_newline_style(value)
    trailing = orig_trailing if result_lines else False
    result = _reconstruct(result_lines, newline, trailing)
    n = end - (start_line - 1)
    return (
        f"Success: deleted {n} line(s) [{start_line}-{end}] from {label!r}."
        f"\n\n{_make_diff(value, result)}",
        result,
    )


def _do_append_lines(args: dict, value: str, label: str) -> tuple[str, str]:
    content = args.get("content")
    if content is None:
        return "Error: 'content' is required for action 'append_lines'.", value
    if not isinstance(content, str):
        return "Error: 'content' must be a string.", value

    new_lines, content_trailing = _split_lines_preserve(content)
    if not new_lines:
        return "Error: 'content' is empty; nothing to append.", value

    orig_lines, _ = _split_lines_preserve(value)
    result_lines = orig_lines + new_lines
    newline = _detect_newline_style(value)
    result = _reconstruct(result_lines, newline, content_trailing)
    return (
        f"Success: appended {len(new_lines)} line(s) to {label!r}."
        f"\n\n{_make_diff(value, result)}",
        result,
    )


def _do_prepend_lines(args: dict, value: str, label: str) -> tuple[str, str]:
    content = args.get("content")
    if content is None:
        return "Error: 'content' is required for action 'prepend_lines'.", value
    if not isinstance(content, str):
        return "Error: 'content' must be a string.", value

    new_lines, content_trailing = _split_lines_preserve(content)
    if not new_lines:
        return "Error: 'content' is empty; nothing to prepend.", value

    orig_lines, orig_trailing = _split_lines_preserve(value)
    result_lines = new_lines + orig_lines
    newline = _detect_newline_style(value)
    trailing = orig_trailing if orig_lines else content_trailing
    result = _reconstruct(result_lines, newline, trailing)
    return (
        f"Success: prepended {len(new_lines)} line(s) to {label!r}."
        f"\n\n{_make_diff(value, result)}",
        result,
    )


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
    "search_replace": _do_search_replace,
    "regex_replace": _do_regex_replace,
    "insert_lines": _do_insert_lines,
    "delete_lines": _do_delete_lines,
    "append_lines": _do_append_lines,
    "prepend_lines": _do_prepend_lines,
}
