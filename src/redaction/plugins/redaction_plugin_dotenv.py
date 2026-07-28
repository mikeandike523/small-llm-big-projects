from __future__ import annotations

import re

from src.redaction.types import RedactionPlugin

# Matches lines like: KEY=value  or  export KEY=value / EXPORT KEY=value.
# The KEY itself must be UPPER_CASE -- that is the entire signal that
# distinguishes an env-style constant from an ordinary lowercase code
# variable (e.g. bash/python "name = value"). Only the "export" keyword is
# case-insensitive (scoped inline flag), so a lowercase KEY can never match.
_DOTENV_LINE_RE = re.compile(r"^\s*(?:(?i:export)\s+)?[A-Z_][A-Z0-9_]*\s*=.*$", re.MULTILINE)

# Redact the value portion of each key=value line. Grammar mirrors _DOTENV_LINE_RE.
_REDACT_VALUE_RE = re.compile(
    r"^(\s*(?:(?i:export)\s+)?[A-Z_][A-Z0-9_]*\s*=)(.+)$",
    re.MULTILINE,
)


def _looks_like_dotenv_path(path: str) -> bool:
    import os
    name = os.path.basename(path).lower()
    return name == ".env" or name.startswith(".env.")


def _is_pure_dotenv_syntax(content: str) -> bool:
    """True only if every non-blank line is a comment or a recognized
    KEY=VALUE dotenv assignment.

    This is a whitelist, not a ratio: a single line that doesn't fit the
    narrow dotenv grammar (bash control flow, function calls, echo
    statements, a shebang, etc.) disqualifies the whole file. Real shell
    scripts routinely contain nothing but UPPER_CASE=value assignment
    lines syntactically identical to dotenv files, so a shebang on the
    first line is treated as an explicit disqualifier even though it is
    comment-shaped -- it is a strong "this is a script, not a config
    file" signal that plain ratio-based sniffing would otherwise miss.
    """
    lines = content.splitlines()
    saw_any_assignment = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if i == 0 and line.startswith("#!"):
            return False
        if line.startswith("#"):
            continue
        if _DOTENV_LINE_RE.match(line):
            saw_any_assignment = True
            continue
        return False
    return saw_any_assignment


class DotenvPlugin(RedactionPlugin):
    """Redacts secret values in .env-style KEY=VALUE files.

    Confidence is split evenly between path and content (see
    RedactionPlugin.score): a ".env"-shaped filename is worth 50%, and
    the content being *exclusively* recognized dotenv syntax (no bash/
    other-language constructs anywhere in the file) is worth the other
    50%. Either signal alone is enough to trigger redaction of the
    (narrowly-matched) assignment lines; neither alone reaches full
    confidence, matching the "file happens to be all UPPER_CASE=value
    lines but isn't actually a .env file" edge case.
    """

    def matches_filepath(self, path: str | None, content: str) -> float:
        if path is None:
            return 0.0
        return 1.0 if _looks_like_dotenv_path(path) else 0.0

    def matches_content(self, path: str | None, content: str) -> float:
        return 1.0 if _is_pure_dotenv_syntax(content) else 0.0

    def redact(self, path: str | None, content: str) -> str:
        return _REDACT_VALUE_RE.sub(r"\1[REDACTED]", content)
