from __future__ import annotations

import re

from src.redaction.types import RedactionPlugin

# Matches lines like: KEY=value  or  EXPORT KEY=value  (case-insensitive export)
_DOTENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?[A-Z_][A-Z0-9_]*\s*=", re.MULTILINE | re.IGNORECASE)

# Redact the value portion of each key=value line
_REDACT_VALUE_RE = re.compile(
    r"^(\s*(?:export\s+)?[A-Z_][A-Z0-9_]*\s*=)(.+)$",
    re.MULTILINE | re.IGNORECASE,
)


def _looks_like_dotenv_path(path: str) -> bool:
    import os
    name = os.path.basename(path).lower()
    return name == ".env" or name.startswith(".env.")


def _dotenv_content_ratio(content: str) -> float:
    """Fraction of non-blank lines that look like KEY=VALUE assignments."""
    lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return 0.0
    matches = sum(1 for l in lines if _DOTENV_LINE_RE.match(l))
    return matches / len(lines)


class DotenvPlugin(RedactionPlugin):
    """Redacts secret values in .env-style KEY=VALUE files."""

    def matches_filepath(self, path: str | None, content: str) -> float:
        if path is None:
            return 0.0
        return 1.0 if _looks_like_dotenv_path(path) else 0.0

    def matches_content(self, path: str | None, content: str) -> float:
        ratio = _dotenv_content_ratio(content)
        # Require at least a meaningful fraction to avoid false positives
        return ratio if ratio >= 0.5 else 0.0

    def redact(self, path: str | None, content: str) -> str:
        return _REDACT_VALUE_RE.sub(r"\1[REDACTED]", content)
