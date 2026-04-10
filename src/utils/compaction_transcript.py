"""
Utilities for formatting LLM exchange sequences into a plain-text transcript
suitable for the compaction summarisation call.

The transcript avoids all tool-call wire format (role: "tool", tool_calls arrays)
so that the compaction model never sees function-call syntax and cannot echo it back
in its summary output.

All truncation thresholds are module-level constants — tune them here.
"""

from __future__ import annotations

import json

from src.utils.session_model import LLMExchange

# ---------------------------------------------------------------------------
# Truncation thresholds (chars)
# ---------------------------------------------------------------------------

TOOL_ARGS_MAX_CHARS = 300
TOOL_RESULT_MAX_CHARS = 500
ASSISTANT_CONTENT_MAX_CHARS = 600
USER_CONTINUATION_MAX_CHARS = 400

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are reading a condensed transcript of a conversation between a user and an AI "
    "assistant that used various tools to complete a task. Some tool arguments and return "
    "values have been truncated for brevity. "
    "Summarise what happened in 2-4 concise sentences: the purpose of the work, the key "
    "actions taken, and the outcomes. Do not reproduce raw data or tool output verbatim."
)

_USER_PROMPT_PREFIX = (
    "Here is the condensed conversation transcript. Summarise it, focusing on the purpose "
    "of the work and the key actions and outcomes -- not the raw data.\n\n"
)

# ---------------------------------------------------------------------------
# Truncation helper
# ---------------------------------------------------------------------------

def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '... (N more)' when trimmed."""
    if len(text) <= max_chars:
        return text
    remaining = len(text) - max_chars
    return text[:max_chars] + f"... ({remaining} more)"


# ---------------------------------------------------------------------------
# Per-exchange formatting
# ---------------------------------------------------------------------------

def _format_args(args: dict) -> str:
    try:
        raw = json.dumps(args, separators=(",", ":"))
    except (TypeError, ValueError):
        raw = str(args)
    return _truncate(raw, TOOL_ARGS_MAX_CHARS)


def _format_exchange(exchange: LLMExchange, index: int) -> str:
    lines: list[str] = [f"[Exchange {index + 1}]"]

    if exchange.assistant_content and exchange.assistant_content.strip():
        text = _truncate(exchange.assistant_content.strip(), ASSISTANT_CONTENT_MAX_CHARS)
        lines.append(f"Assistant Message: {text}")

    for tc in exchange.tool_calls:
        lines.append(f"Tool Call: {tc.name}")
        lines.append(f"  Args:   {_format_args(tc.args)}")
        result = _truncate((tc.result or "").strip(), TOOL_RESULT_MAX_CHARS)
        lines.append(f"  Result: {result}")

    if exchange.user_continuation:
        text = _truncate(exchange.user_continuation.strip(), USER_CONTINUATION_MAX_CHARS)
        lines.append(f"User Message: {text}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_compaction_messages(exchanges: list[LLMExchange]) -> list[dict]:
    """
    Build a 2-message list [system, user] for the compaction LLM call.

    The transcript is plain text — no tool-call wire format, no role: "tool"
    messages. Safe to feed to any model regardless of tool-calling support.
    """
    parts = [_format_exchange(ex, i) for i, ex in enumerate(exchanges)]
    transcript = "\n\n".join(parts)

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": _USER_PROMPT_PREFIX + transcript},
    ]
