"""
Registry of which wire dialect a real-OpenAI model name should use:
Chat Completions (`/chat/completions`) or the Responses API (`/responses`).

Why this exists as its own file: it's pure data about OpenAI's model catalog,
not wire-protocol logic, and it will need updating independently of
dialect.py every time OpenAI ships a new reasoning-capable model family --
keeping it separate means that update never touches the dialect code itself.

Only consulted for real OpenAI -- dialect.py's detect_dialect() gates this
registry behind "is the provider/endpoint actually OpenAI's own API", never
for OpenRouter (which fronts many providers' models behind one OpenAI-shaped
endpoint and has its own reasoning convention entirely -- see
OpenRouterDialect) or vLLM/other self-hosted OpenAI-compatible servers (which
don't have a `/responses` route at all, regardless of what a locally-served
model happens to be named).

Chat Completions is always a safe default for any model not listed here --
it just won't expose reasoning content for models that have it (see the
TODO(reasoning) note in dialect.py). Responses API is only worth routing to
for models that actually support server-side reasoning items; add a model
family below once you confirm it needs Responses to surface reasoning.

Prefixes, not just exact names: OpenAI model names carry version/date
suffixes (e.g. "o3-mini", "gpt-5-codex", "gpt-5.1-2026-01-15"), so entries
here match either an exact name or a "<entry>-..." prefix (see
uses_responses_api below) rather than requiring every dated variant to be
listed individually.

Keep this list current as OpenAI ships new model families -- it reflects
model names known as of this writing and will drift out of date.
"""

from __future__ import annotations

RESPONSES_API_MODEL_PREFIXES: frozenset[str] = frozenset(
    {
        # o-series reasoning models
        "o1",
        "o3",
        "o4-mini",
        # gpt-5 reasoning family (gpt-5, gpt-5-mini, gpt-5-codex, gpt-5.x, ...)
        "gpt-5",
    }
)


def uses_responses_api(model: str | None) -> bool:
    """
    True if `model` is a known reasoning-capable OpenAI model family that
    should be routed to the Responses API instead of Chat Completions.
    Matches an exact registry entry or the entry followed by any non-
    alphanumeric boundary character -- "o3-mini" and "gpt-5.1-2026-01-15"
    both match "o3"/"gpt-5" without listing every dated/minor-version
    variant, while "gpt-50" does not falsely match "gpt-5". False (including
    for None/empty) defaults callers to Chat Completions.
    """
    if not model:
        return False
    name = model.strip().lower()
    for prefix in RESPONSES_API_MODEL_PREFIXES:
        if name == prefix:
            return True
        if name.startswith(prefix) and not name[len(prefix)].isalnum():
            return True
    return False
