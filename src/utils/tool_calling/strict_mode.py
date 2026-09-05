"""Sets the `strict` field on outgoing tool definitions.

Driven by src/utils/llm/dialect.py:should_force_tool_strict() (automatic,
per-dialect/model) and system.override_strict_tool_def (manual escape
hatch) -- see StreamingLLM._build_base_payload() in streaming.py, the
single point where both are resolved into one decision.

Per OpenAI's function-calling docs, `strict` is a sibling of `type`/`name`/
`parameters` in the tool definition: nested under `function` for Chat
Completions-shaped tool defs (what this project's ALL_TOOL_DEFINITIONS
always uses), flattened to the top level for the Responses API. Setting it
here, under `function`, is correct for Chat Completions dialects as-is (they
pass `tools` through unmodified); dialect_openai_responses.py's
_convert_tools() propagates this same key into its flattened shape.
"""
from __future__ import annotations

import copy


def set_tool_defs_strict(tool_defs: list[dict], value: bool) -> list[dict]:
    """Return a deep copy of tool_defs with function.strict explicitly set to `value`."""
    result = copy.deepcopy(tool_defs)
    for tool in result:
        fn = tool.get("function")
        if isinstance(fn, dict):
            fn["strict"] = value
    return result
