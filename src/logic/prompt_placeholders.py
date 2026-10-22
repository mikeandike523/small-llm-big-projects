"""``{{ NAME }}`` placeholder interpolation for the system prompt and skills.

Only UPPER_SNAKE_CASE names are recognised, so lowercase template syntax
that a skill happens to quote (Jinja, Handlebars, ...) passes through
untouched. A recognised-looking name with no value is left as written and
reported through ``on_unknown``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.utils.session_dirs import get_session_scratchpad_dir

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class PlaceholderContext:
    values: dict[str, str] = field(default_factory=dict)
    # Called as on_unknown(name, source) for each unresolved placeholder.
    on_unknown: Callable[[str, str], None] | None = None


def build_placeholder_values(
    session_id: str, initial_cwd: str | None
) -> dict[str, str]:
    return {
        "SCRATCHPAD_PATH": get_session_scratchpad_dir(session_id),
        "SESSION_ID": session_id,
        "INITIAL_CWD": (initial_cwd or "").replace("\\", "/"),
        "HOME": str(Path.home()).replace("\\", "/"),
    }


def interpolate_placeholders(
    text: str, ctx: PlaceholderContext | None, source: str
) -> str:
    """Replace known ``{{ NAME }}`` placeholders in *text*. *source* names the
    text (e.g. a skill filename) for unknown-placeholder reports."""
    if ctx is None:
        return text
    unknown: list[str] = []

    def _sub(match: re.Match) -> str:
        name = match.group(1)
        if name in ctx.values:
            return ctx.values[name]
        if name not in unknown:
            unknown.append(name)
        return match.group(0)

    result = _PLACEHOLDER_RE.sub(_sub, text)
    if ctx.on_unknown is not None:
        for name in unknown:
            ctx.on_unknown(name, source)
    return result
