from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Fuzzy matching configuration
# ---------------------------------------------------------------------------

# Per-line minimum ratio passes.  Each pass has a min and max leniency that
# scales linearly with the number of before-lines from MIN (at 1 line) to MAX
# (at MAX_LENIENCY_AT_LINES+).  Every line in the candidate window must meet
# the threshold; a single low-scoring pair fails the whole window.
MAX_LENIENCY_LAX = 0.15
MIN_LENIENCY_LAX = 0.05
MAX_LENIENCY_MID = 0.05
MIN_LENIENCY_MID = 0.01
MAX_LENIENCY_AT_LINES = 15

# ---------------------------------------------------------------------------
# LineGroup — parsed, validated hunk body
# ---------------------------------------------------------------------------

_NO_NEWLINE_MARKER = "\\ No newline at end of file"


@dataclass
class LineGroup:
    """A parsed hunk body: tagged content lines plus trailing-newline state.

    tagged: list of (prefix, content) where prefix is '+', '-', or ' '.
            '\\ No newline at end of file' markers are never stored here;
            they are consumed during parsing and expressed via the flags below.
    new_has_trailing_newline: whether the new (after-apply) side ends with a newline.
    old_has_trailing_newline: whether the old (before-apply) side ends with a newline.
    """

    tagged: list[tuple[str, str]]
    new_has_trailing_newline: bool = True
    old_has_trailing_newline: bool = True

    def before_lines(self) -> list[str]:
        """Content of context + remove lines — what the file must contain at the match site."""
        return [c for p, c in self.tagged if p in ("-", " ")]


def _parse_hunk_body(body_text: str) -> LineGroup:
    """Parse a hunk body string into a LineGroup.

    Two-pass approach:
      Pass 1 — collect raw (prefix, content) pairs; bare blank lines become context (' ').
      Pass 2 — locate, validate, and strip '\\' (no-newline) markers:
                * must form a contiguous tail (none may appear mid-hunk)
                * must be exactly _NO_NEWLINE_MARKER
                * at most 2 per hunk (one per side)
                Sets old_/new_has_trailing_newline based on which side each marker follows.
    """
    # Pass 1 — collect
    raw: list[tuple[str, str]] = []
    for line in body_text.splitlines():
        if not line:
            raw.append((" ", ""))
        elif line[0] in ("+", "-", " "):
            raw.append((line[0], line[1:]))
        elif line[0] == "\\":
            raw.append(("\\", line[1:]))
        else:
            raise ValueError(f"invalid hunk line prefix {line[0]!r} in: {line!r}")

    # Pass 2 — validate '\' entries
    bs_indices = [i for i, (p, _) in enumerate(raw) if p == "\\"]

    if bs_indices:
        first = bs_indices[0]
        # Must be a contiguous tail
        if bs_indices != list(range(first, len(raw))):
            raise ValueError(
                "no-newline marker ('\\\\') appears mid-hunk; "
                "it may only appear at the very end of a hunk section"
            )
        if len(bs_indices) > 2:
            raise ValueError(
                f"too many no-newline markers in hunk: {len(bs_indices)} (max 2)"
            )
        for i in bs_indices:
            full = "\\" + raw[i][1]
            if full != _NO_NEWLINE_MARKER:
                raise ValueError(f"unrecognized no-newline marker: {full!r}")

    # Determine which side each marker affects by looking at the preceding non-'\' prefix
    old_has_trailing_newline = True
    new_has_trailing_newline = True
    prev_prefix: str | None = None
    for prefix, _ in raw:
        if prefix != "\\":
            prev_prefix = prefix
        else:
            if prev_prefix in ("-", " "):
                old_has_trailing_newline = False
            if prev_prefix in ("+", " "):
                new_has_trailing_newline = False

    tagged = [(p, c) for p, c in raw if p != "\\"]
    return LineGroup(
        tagged=tagged,
        new_has_trailing_newline=new_has_trailing_newline,
        old_has_trailing_newline=old_has_trailing_newline,
    )


# ---------------------------------------------------------------------------
# Hunk data model
# ---------------------------------------------------------------------------


@dataclass
class ParsedHunk:
    start: int | None  # +start from @@ header; only set for pure-insertion hunks
    group: LineGroup


# ---------------------------------------------------------------------------
# Line-splitting helpers
# ---------------------------------------------------------------------------


def _split_lines_preserve(text: str) -> tuple[list[str], bool]:
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
# Diff helper
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

        new_start = int(m.group(3))
        i += 1

        body_lines: list[str] = []
        while i < n_lines:
            if _HUNK_HEADER_RE.match(raw_lines[i]):
                break
            if any(raw_lines[i].startswith(p) for p in _FILE_HEADER_PREFIXES):
                break
            body_lines.append(raw_lines[i])
            i += 1

        group = _parse_hunk_body("\n".join(body_lines))
        is_pure_insertion = bool(group.tagged) and all(
            p == "+" for p, _ in group.tagged
        )
        hunks.append(ParsedHunk(
            start=new_start if is_pure_insertion else None,
            group=group,
        ))

    return hunks


# ---------------------------------------------------------------------------
# Context matching — per-line minimum ratio
# ---------------------------------------------------------------------------


def _compute_leniency(
    anchor_lines: int, max_leniency: float, min_leniency: float = 0.0
) -> float:
    """Scale leniency linearly from *min_leniency* (1 line) to *max_leniency* (MAX_LENIENCY_AT_LINES+)."""
    t = (
        min(max(anchor_lines - 1, 0), MAX_LENIENCY_AT_LINES - 1)
        / (MAX_LENIENCY_AT_LINES - 1)
    )
    return min_leniency + (max_leniency - min_leniency) * t


def _find_context_hits(
    file_lines: list[str], before_lines: list[str]
) -> tuple[list[int], str]:
    """Find positions in *file_lines* where *before_lines* matches.

    Comparison is right-stripped per line.  Each candidate window must have
    every line pair meet the ratio threshold (minimum, not mean) — a single
    poor-scoring pair fails the whole window.  This makes dropped or shifted
    lines fail reliably rather than being absorbed by a high-scoring majority.

    Scans exact -> mid -> lax, returning on the first non-empty result.
    Returns (hit_positions, label).
    """
    n = len(before_lines)
    norm_before = [b.rstrip() for b in before_lines]
    total = len(file_lines)

    def _candidate(start: int) -> list[str]:
        return [file_lines[start + k].rstrip() for k in range(n)]

    def _exact_hits() -> list[int]:
        return [
            i for i in range(total - n + 1)
            if _candidate(i) == norm_before
        ]

    def _min_ratio(start: int) -> float:
        return min(
            difflib.SequenceMatcher(None, b, c).ratio()
            for b, c in zip(norm_before, _candidate(start))
        )

    def _fuzzy_hits(threshold: float) -> list[int]:
        return [
            i for i in range(total - n + 1)
            if _min_ratio(i) >= threshold
        ]

    leniency_lax = _compute_leniency(n, MAX_LENIENCY_LAX, MIN_LENIENCY_LAX)
    leniency_mid = _compute_leniency(n, MAX_LENIENCY_MID, MIN_LENIENCY_MID)

    hits_exact = _exact_hits()
    if hits_exact:
        return hits_exact, "normalized"

    hits_mid = _fuzzy_hits(1.0 - leniency_mid)
    if hits_mid:
        return hits_mid, "fuzzy"

    hits_lax = _fuzzy_hits(1.0 - leniency_lax)
    return hits_lax, "fuzzy (lax)"


# ---------------------------------------------------------------------------
# Location preview helper (used in ambiguous-match error messages)
# ---------------------------------------------------------------------------


def _location_preview(file_lines: list[str], start: int, count: int) -> str:
    if count == 0 or start >= len(file_lines):
        return "(empty)"
    first = file_lines[start]
    return first + (" ..." if count > 1 else "")


_MATCH_LABEL = {
    "normalized": "exact",
    "fuzzy": "fuzzy/mid",
    "fuzzy (lax)": "fuzzy/lax",
}


# ---------------------------------------------------------------------------
# Apply hunks
# ---------------------------------------------------------------------------


def _apply_edits(original_text: str, hunks: list[ParsedHunk]) -> str:
    """Apply a list of parsed hunks to original_text.

    Context lines are taken from the actual file via a file pointer, never
    from the patch text.  This prevents LLM hallucinations in context lines
    from corrupting the output, and ensures the line count consumed from the
    file exactly matches the number of context+remove lines in the hunk.

    EOL style of the result always matches the original file.
    has_trailing_newline for the result is taken from the last hunk that
    touches the end of the file; otherwise the original file's state is kept.
    """
    newline = _detect_newline_style(original_text)
    file_lines, had_trailing_nl = _split_lines_preserve(original_text)

    total = len(hunks)
    statuses: list[str] = []
    has_failure = False
    final_trailing_nl = had_trailing_nl

    def _fail(n: int, hunk: ParsedHunk, reason: str) -> None:
        nonlocal has_failure
        has_failure = True
        hunk_repr = "\n".join(p + c for p, c in hunk.group.tagged)
        statuses.append(
            f"Hunk #{n} of {total} Failed — {reason}\n"
            f"Detected hunk text:\n{hunk_repr}"
        )

    for n, hunk in enumerate(hunks, start=1):
        group = hunk.group

        if not group.tagged:
            _fail(n, hunk, "empty hunk body.")
            continue

        if all(p == " " for p, _ in group.tagged):
            _fail(
                n, hunk,
                "hunk contains only context lines (no '+' or '-' lines); "
                "nothing to change. Add the lines to add/remove, or omit this hunk entirely.",
            )
            continue

        before_lines = group.before_lines()

        # Pure insertion: no context or removed lines to locate on
        if not before_lines:
            if hunk.start is None:
                _fail(
                    n, hunk,
                    "no context or removed lines to anchor on, and no insertion "
                    "position available. Include at least one context (' ') or "
                    "removed ('-') line, or ensure the @@ header contains a valid line number.",
                )
                continue
            apply_at = min(max(hunk.start - 1, 0), len(file_lines))
            additions = [c for p, c in group.tagged if p == "+"]
            if apply_at >= len(file_lines):
                final_trailing_nl = group.new_has_trailing_newline
            file_lines = file_lines[:apply_at] + additions + file_lines[apply_at:]
            statuses.append(
                f"Hunk #{n} of {total}: Valid (pure insertion at line {hunk.start})."
            )
            continue

        hits, match_method = _find_context_hits(file_lines, before_lines)

        if not hits:
            _fail(n, hunk, "context not found at any tolerance level.")
            continue
        if len(hits) > 1:
            level = _MATCH_LABEL.get(match_method, match_method)
            previews = "\n".join(
                f"  line {h + 1}: {_location_preview(file_lines, h, len(before_lines))}"
                for h in hits
            )
            _fail(
                n, hunk,
                f"context matches {len(hits)} locations ({level}); "
                f"add more surrounding lines to disambiguate:\n{previews}",
            )
            continue

        apply_at = hits[0]
        result_lines: list[str] = []
        file_ptr = apply_at

        for prefix, content in group.tagged:
            if prefix == " ":
                result_lines.append(file_lines[file_ptr])
                file_ptr += 1
            elif prefix == "-":
                file_ptr += 1
            else:  # '+'
                result_lines.append(content)

        if file_ptr == len(file_lines):
            final_trailing_nl = group.new_has_trailing_newline

        file_lines = file_lines[:apply_at] + result_lines + file_lines[file_ptr:]
        statuses.append(f"Hunk #{n} of {total}: Valid ({match_method} match).")

    if has_failure:
        status_lines = "\n\n".join(
            s.replace(": Valid", ": Valid, not applied") for s in statuses
        )
        raise ValueError(
            f"At least one hunk is invalid; no changes applied.\n\n{status_lines}"
        )

    result = newline.join(file_lines)
    if final_trailing_nl and file_lines:
        result += newline
    return result
