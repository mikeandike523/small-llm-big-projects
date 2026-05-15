from __future__ import annotations

import difflib
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Fuzzy matching configuration
# ---------------------------------------------------------------------------

# Maximum allowed per-line error fraction for fuzzy context matching (step 3).
# A value of 0.10 means each context line must be >= 90% similar to its
# counterpart in the target. Raise to allow more forgiveness; lower to reduce
# false-positive matches on structurally similar code.
FUZZY_MATCH_MAX_ERROR = 0.10

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


def _find_context_hits(lines: list[str], before: list[str]) -> tuple[list[int], str]:
    """Find positions in *lines* where *before* matches, using progressive matching.

    Step 0+1 (always): strip leading/trailing whitespace from each line before
    comparing (EOL is already normalised by _split_lines_preserve / splitlines).

    Step 3 (fallback): per-line fuzzy via SequenceMatcher — a position is
    accepted only when ALL context lines score >= 1 - FUZZY_MATCH_MAX_ERROR.

    Returns (hit_positions, label) where label is "normalized" or "fuzzy".
    Empty hit_positions means no match was found at any level.
    """
    n = len(before)
    norm_lines = [line.strip() for line in lines]
    norm_before = [line.strip() for line in before]

    # Step 0+1 — normalised exact match
    hits = [
        i
        for i in range(len(lines))
        if i + n <= len(lines) and norm_lines[i : i + n] == norm_before
    ]
    if hits:
        return hits, "normalized"

    # Step 3 — per-line fuzzy (all lines must clear the threshold)
    threshold = 1.0 - FUZZY_MATCH_MAX_ERROR
    fuzzy_hits = [
        i
        for i in range(len(lines))
        if i + n <= len(lines)
        and all(
            difflib.SequenceMatcher(None, norm_before[j], norm_lines[i + j]).ratio()
            >= threshold
            for j in range(n)
        )
    ]
    return fuzzy_hits, "fuzzy"


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

    total = len(edits)
    statuses: list[str] = []  # one entry per edit
    has_failure = False

    for n, edit in enumerate(edits, start=1):
        edit_text = edit.get("text", "")
        position = edit.get("position")
        before, after = _parse_simple_edit(edit_text)

        if not before:
            if position is None:
                statuses.append(
                    f"Edit {n} of {total}: Failed — no context or removed lines to anchor on, "
                    "and no 'position' given. Either include at least one context line (space "
                    "prefix) or removed line ('-'), or set 'position' for pure insertions."
                )
                has_failure = True
                continue
            apply_at = min(max(position - 1, 0), len(lines))
            lines = lines[:apply_at] + after + lines[apply_at:]
            statuses.append(f"Edit {n} of {total}: Valid.")
        else:
            hits, match_method = _find_context_hits(lines, before)

            if not hits:
                statuses.append(
                    f"Edit {n} of {total}: Failed — context did not match anywhere in the target."
                )
                has_failure = True
                continue
            if len(hits) > 1:
                statuses.append(
                    f"Edit {n} of {total}: Failed — context matches multiple locations "
                    f"({[h + 1 for h in hits]}); ambiguous."
                )
                has_failure = True
                continue

            apply_at = hits[0]
            lines = lines[:apply_at] + after + lines[apply_at + len(before) :]
            statuses.append(f"Edit {n} of {total}: Valid ({match_method} match).")

    if has_failure:
        status_lines = "\n".join(
            s.replace(": Valid", ": Valid, not applied") for s in statuses
        )
        raise ValueError(
            f"At least one edit is invalid; no changes applied.\n{status_lines}"
        )

    ends_with_nl = had_trailing_nl if trailing_newline is None else trailing_newline
    result = newline.join(lines)
    if ends_with_nl:
        result += newline
    return result
