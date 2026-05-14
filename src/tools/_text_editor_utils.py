from __future__ import annotations

import difflib
from typing import List, Tuple

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
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts = parts[:-1]
    lines = [p[:-1] if p.endswith("\r") else p for p in parts]
    return lines, had_trailing_newline


# ---------------------------------------------------------------------------
# EOL style helpers
# ---------------------------------------------------------------------------


def _detect_newline_style(text: str) -> str:
    """Return \\r\\n if the text contains any CRLF, else \\n."""
    return "\r\n" if "\r\n" in text else "\n"


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
    diff_lines = list(
        difflib.unified_diff(
            before_lines, after_lines, fromfile="before", tofile="after", lineterm=""
        )
    )
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
        if raw.startswith("+"):
            after.append(raw[1:])
        elif raw.startswith("-"):
            before.append(raw[1:])
        else:
            content = raw[1:] if raw.startswith(" ") else raw
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
                i
                for i in range(len(lines))
                if (
                    i + len(before_keys) <= len(lines)
                    and [s.rstrip() for s in lines[i : i + len(before_keys)]]
                    == before_keys
                )
            ]

            if not hits:
                raise ValueError(
                    f"Edit {n}: context did not match anywhere in the target."
                )
            if len(hits) > 1:
                raise ValueError(
                    f"Edit {n}: context matches multiple locations "
                    f"({[h + 1 for h in hits]}); ambiguous, refusing to apply."
                )

            apply_at = hits[0]
            lines = lines[:apply_at] + after + lines[apply_at + len(before) :]

    ends_with_nl = had_trailing_nl if trailing_newline is None else trailing_newline
    result = newline.join(lines)
    if ends_with_nl:
        result += newline
    return result
