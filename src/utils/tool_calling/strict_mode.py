"""Diagnostic hotfix gated behind system.hotfix_gpt_strict_tool_def -- forces
strict: false onto every outgoing tool definition, instead of omitting the
field (today's default), to test whether a model over-populating optional
tool arguments is caused by it inferring strict mode when the field is
absent, independent of system.hotfix_gpt_aggressive_arg_fill's actual fix.

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


def force_tool_defs_non_strict(tool_defs: list[dict]) -> list[dict]:
    """Return a deep copy of tool_defs with function.strict explicitly set to False."""
    result = copy.deepcopy(tool_defs)
    for tool in result:
        fn = tool.get("function")
        if isinstance(fn, dict):
            fn["strict"] = False
    return result
