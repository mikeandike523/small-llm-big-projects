from __future__ import annotations

import re

from src.redaction.types import RedactionPlugin

# Patterns that suggest sensitive content regardless of file type
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(private[_-]?key)\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
]

# Used during redact: replace matched value portion with [REDACTED]
_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)((api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*)\S+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)((password|passwd|pwd)\s*[:=]\s*)\S+"),
        r"\1[REDACTED]",
    ),
]


def _sensitive_match_score(content: str) -> float:
    """Fraction of sensitive patterns that appear in the content, capped at 1.0."""
    if not content.strip():
        return 0.0
    hits = sum(1 for p in _SENSITIVE_PATTERNS if p.search(content))
    return min(hits / len(_SENSITIVE_PATTERNS), 1.0)


class GeneralPlugin(RedactionPlugin):
    """Catches generic sensitive patterns (API keys, passwords, tokens) in any file.

    Not a true fallback: if it scores 0.0, no plugin applies and the engine
    returns the content unchanged.
    """

    def matches_filepath(self, path: str | None, content: str) -> float:
        return 0.0  # path-agnostic; let content score drive selection

    def matches_content(self, path: str | None, content: str) -> float:
        return _sensitive_match_score(content)

    def redact(self, path: str | None, content: str) -> str:
        result = content
        for pattern, replacement in _REDACT_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
