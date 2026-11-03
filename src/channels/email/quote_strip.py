"""Conservative removal of the quoted history at the bottom of a reply.

Only a *trailing* block that starts at an unambiguous marker is removed:

* an ``On ... wrote:`` attribution line (Gmail, Apple Mail, Thunderbird; it
  may be wrapped over two lines) followed only by ``>``-quoted or blank lines;
* an Outlook header block (``From:`` then ``Sent:`` plus ``To:``/``Subject:``
  within the next few lines), optionally preceded by an underscore divider;
* text that matches an answer this session already emailed in the thread.

Anything else, including inline replies interleaved with quotes, is returned
unchanged: the worst case is extra tokens, never lost content.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_WROTE_RE = re.compile(r"^\s*On\s.{1,300}\swrote:\s*$", re.IGNORECASE)
_OUTLOOK_FROM_RE = re.compile(r"^\s*\**From:\**\s+\S", re.IGNORECASE)
_OUTLOOK_SENT_RE = re.compile(r"^\s*\**(Sent|Date):\**\s+\S", re.IGNORECASE)
_OUTLOOK_TO_RE = re.compile(r"^\s*\**(To|Subject):\**\s+\S", re.IGNORECASE)
_DIVIDER_RE = re.compile(r"^\s*_{8,}\s*$")
_SENT_MATCH_PREFIX_CHARS = 60


def _is_quoted_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith(">")


def _attribution_start(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        joined_two = None
        if i + 1 < len(lines):
            joined_two = f"{line.rstrip()} {lines[i + 1].strip()}"
        if _WROTE_RE.match(line):
            end = i + 1
        elif joined_two is not None and _WROTE_RE.match(joined_two):
            end = i + 2
        else:
            continue
        rest = lines[end:]
        if any(line.strip() for line in rest) and all(
            _is_quoted_or_blank(line) for line in rest
        ):
            return i
    return None


def _outlook_start(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if not _OUTLOOK_FROM_RE.match(line):
            continue
        window = lines[i + 1 : i + 6]
        if any(_OUTLOOK_SENT_RE.match(w) for w in window) and any(
            _OUTLOOK_TO_RE.match(w) for w in window
        ):
            start = i
            if i > 0 and _DIVIDER_RE.match(lines[i - 1]):
                start = i - 1
            return start
    return None


def _normalize(text: str) -> str:
    unquoted = "\n".join(line.lstrip("> ").rstrip() for line in text.splitlines())
    return " ".join(unquoted.split())


def _sent_text_start(lines: list[str], sent_texts: Sequence[str]) -> int | None:
    prefixes = [
        _normalize(text)[:_SENT_MATCH_PREFIX_CHARS]
        for text in sent_texts
        if len(_normalize(text)) >= 20
    ]
    if not prefixes:
        return None
    for i in range(1, len(lines)):
        tail = _normalize("\n".join(lines[i:]))
        if any(tail.startswith(prefix) for prefix in prefixes):
            start = i
            # Include an attribution line directly above the quoted answer.
            while start > 0 and not lines[start - 1].strip():
                start -= 1
            if start > 0 and lines[start - 1].rstrip().lower().endswith("wrote:"):
                start -= 1
            return start
    return None


def strip_trailing_quote(text: str, sent_texts: Sequence[str] = ()) -> str:
    """The reply without its trailing quoted history, when that is certain."""
    lines = text.splitlines()
    candidates = [
        start
        for start in (
            _attribution_start(lines),
            _outlook_start(lines),
            _sent_text_start(lines, sent_texts),
        )
        if start is not None
    ]
    if not candidates:
        return text
    kept = "\n".join(lines[: min(candidates)]).rstrip()
    # Never return nothing: a reply that is all quote is passed whole.
    return kept if kept.strip() else text
