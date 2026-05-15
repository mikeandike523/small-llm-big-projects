from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Fuzzy matching configuration
# ---------------------------------------------------------------------------

# Maximum allowed per-line error fraction for fuzzy context matching (step 3).
# A value of 0.05 means each context line must be >= 95% similar to its
# counterpart in the target.
FUZZY_MATCH_MAX_ERROR = 0.05

# ---------------------------------------------------------------------------
# Hunk data model
# ---------------------------------------------------------------------------


@dataclass
class ParsedHunk:
    start: int | None  # +start from @@ header; set only for pure-insertion hunks
    text: str          # processed hunk body (blank lines resolved); shown in errors


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
# Patch parsing
# ---------------------------------------------------------------------------

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE_HEADER_PREFIXES = ("diff ", "index ", "--- ", "+++ ")


def _is_no_newline_marker(line: str) -> bool:
    return line.startswith("\\ ")


def _parse_patch_file(patch: str) -> list[ParsedHunk]:
    """Parse a unified diff string into a list of ParsedHunk objects."""
    raw_lines = patch.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    hunks: list[ParsedHunk] = []
    i = 0
    n_lines = len(raw_lines)

    while i < n_lines:
        line = raw_lines[i]

        if any(line.startswith(p) for p in _FILE_HEADER_PREFIXES):
            i += 1
            continue

        m = _HUNK_HEADER_RE.match(line)
        if not m:
            i += 1
            continue

        old_len = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_len = int(m.group(4)) if m.group(4) is not None else 1
        i += 1

        body_lines: list[str] = []
        while i < n_lines:
            if _HUNK_HEADER_RE.match(raw_lines[i]):
                break
            if any(raw_lines[i].startswith(p) for p in _FILE_HEADER_PREFIXES):
                break
            body_lines.append(raw_lines[i])
            i += 1

        # Exclude no-newline markers from length counts
        countable = [l for l in body_lines if not _is_no_newline_marker(l)]

        # Count including bare blank lines as potential context
        old_with_blanks = sum(
            1 for l in countable
            if l.startswith("-") or l.startswith(" ") or l == ""
        )
        new_with_blanks = sum(
            1 for l in countable
            if l.startswith("+") or l.startswith(" ") or l == ""
        )

        if old_with_blanks == old_len and new_with_blanks == new_len:
            # Blank lines are genuine context; normalise to space-prefix form
            resolved = [(" " if l == "" else l) for l in body_lines]
        else:
            # Lengths are hallucinated; strip bare blank lines (keep prefixed blanks)
            resolved = [l for l in body_lines if l or _is_no_newline_marker(l)]

        text = "\n".join(resolved)

        # Pure insertion: no context or removed lines present
        non_marker = [l for l in resolved if not _is_no_newline_marker(l)]
        is_pure_insertion = bool(non_marker) and not any(
            l.startswith(" ") or l.startswith("-") for l in non_marker
        )

        hunks.append(ParsedHunk(
            start=new_start if is_pure_insertion else None,
            text=text,
        ))

    return hunks


# ---------------------------------------------------------------------------
# Hunk body parsing (strict unified diff format)
# ---------------------------------------------------------------------------


def _parse_simple_edit(
    edit_text: str,
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Parse a hunk body into (before, after) with per-line has_newline flags.

    '+' prefix  → after only
    '-' prefix  → before only
    ' ' prefix  → context (before and after)
    '\\ '       → No newline at end of file; clears has_newline on the preceding line
    any other   → raises ValueError
    """
    before: list[tuple[str, bool]] = []
    after: list[tuple[str, bool]] = []
    last_in_before = False
    last_in_after = False

    for raw in edit_text.splitlines():
        if _is_no_newline_marker(raw):
            if last_in_before and before:
                before[-1] = (before[-1][0], False)
            if last_in_after and after:
                after[-1] = (after[-1][0], False)
            last_in_before = False
            last_in_after = False
        elif raw.startswith("+"):
            after.append((raw[1:], True))
            last_in_before = False
            last_in_after = True
        elif raw.startswith("-"):
            before.append((raw[1:], True))
            last_in_before = True
            last_in_after = False
        elif raw.startswith(" "):
            content = raw[1:]
            before.append((content, True))
            after.append((content, True))
            last_in_before = True
            last_in_after = True
        else:
            raise ValueError(f"Invalid line prefix in hunk: {raw!r}")

    return before, after


# ---------------------------------------------------------------------------
# Context matching
# ---------------------------------------------------------------------------


def _block_str(lines: list[tuple[str, bool]]) -> str:
    """Join lines into one string using \\n where has_newline is True, nothing where False."""
    return "".join(c + ("\n" if nl else "") for c, nl in lines)


def _find_context_hits(
    lines: list[tuple[str, bool]], before: list[tuple[str, bool]]
) -> tuple[list[int], str]:
    """Find positions in *lines* where *before* matches.

    Each candidate window and *before* are assembled into a single block string
    (per-line strip for normalisation; \\n inserted where has_newline is True).
    The 95% SequenceMatcher threshold applies to the block as a whole, not per line.

    Step 1: normalised exact match.
    Step 2 (fallback): fuzzy block match via SequenceMatcher >= 1 - FUZZY_MATCH_MAX_ERROR.

    Returns (hit_positions, label) where label is 'normalized' or 'fuzzy'.
    """
    n = len(before)
    norm_before = _block_str([(c.strip(), nl) for c, nl in before])

    exact_hits = [
        i
        for i in range(len(lines) - n + 1)
        if _block_str([(c.strip(), nl) for c, nl in lines[i : i + n]]) == norm_before
    ]
    if exact_hits:
        return exact_hits, "normalized"

    threshold = 1.0 - FUZZY_MATCH_MAX_ERROR
    fuzzy_hits = [
        i
        for i in range(len(lines) - n + 1)
        if difflib.SequenceMatcher(
            None,
            norm_before,
            _block_str([(c.strip(), nl) for c, nl in lines[i : i + n]]),
        ).ratio() >= threshold
    ]
    return fuzzy_hits, "fuzzy"


# ---------------------------------------------------------------------------
# Apply hunks
# ---------------------------------------------------------------------------


def _apply_edits(original_text: str, hunks: list[ParsedHunk]) -> str:
    """Apply a list of parsed hunks to original_text.

    EOL style always matches the original file.
    Per-line has_newline flags (from '\\ No newline at end of file' markers)
    trump the original file's trailing-newline state for affected lines.
    """
    newline = _detect_newline_style(original_text)
    raw_lines, had_trailing_nl = _split_lines_preserve(original_text)

    lines: list[tuple[str, bool]] = [(c, True) for c in raw_lines]
    if lines:
        lines[-1] = (lines[-1][0], had_trailing_nl)

    total = len(hunks)
    statuses: list[str] = []
    has_failure = False

    def _fail(n: int, hunk: ParsedHunk, reason: str) -> None:
        nonlocal has_failure
        has_failure = True
        statuses.append(
            f"Hunk #{n} of {total} Failed — {reason}\n"
            f"Detected hunk text:\n{hunk.text}"
        )

    for n, hunk in enumerate(hunks, start=1):
        try:
            before, after = _parse_simple_edit(hunk.text)
        except ValueError as exc:
            _fail(n, hunk, str(exc))
            continue

        if before and before == after:
            _fail(
                n, hunk,
                "hunk contains only context lines (no '+' or '-' lines); "
                "nothing to change. Add the lines to add/remove, or omit this hunk entirely.",
            )
            continue

        if not before:
            if hunk.start is None:
                _fail(
                    n, hunk,
                    "no context or removed lines to anchor on, and no insertion "
                    "position available. Include at least one context (' ') or "
                    "removed ('-') line, or ensure the @@ header contains a valid line number.",
                )
                continue
            apply_at = min(max(hunk.start - 1, 0), len(lines))
            lines = lines[:apply_at] + after + lines[apply_at:]
            statuses.append(
                f"Hunk #{n} of {total}: Valid (pure insertion at line {hunk.start})."
            )
            continue

        hits, match_method = _find_context_hits(lines, before)

        if not hits:
            _fail(n, hunk, "context did not match anywhere in the target.")
            continue
        if len(hits) > 1:
            _fail(
                n, hunk,
                f"context matches multiple locations ({[h + 1 for h in hits]}); ambiguous.",
            )
            continue

        apply_at = hits[0]
        lines = lines[:apply_at] + after + lines[apply_at + len(before):]
        statuses.append(f"Hunk #{n} of {total}: Valid ({match_method} match).")

    if has_failure:
        status_lines = "\n\n".join(
            s.replace(": Valid", ": Valid, not applied") for s in statuses
        )
        raise ValueError(
            f"At least one hunk is invalid; no changes applied.\n\n{status_lines}"
        )

    result = ""
    for content, has_nl in lines:
        result += content + (newline if has_nl else "")
    return result
