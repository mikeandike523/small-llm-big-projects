"""
Helper to strip down a conversation for context-limit / timeout retry.

Each tool module may declare:
  LEAVE_OUT: str   ("KEEP" | "PARAMS_ONLY" | "OMIT" | "SHORT")
  TOOL_SHORT_AMOUNT: int  (only used when LEAVE_OUT == "SHORT")

Policy semantics
----------------
KEEP         — no change (default when attribute is absent)
PARAMS_ONLY  — keep the assistant tool_calls entry (params visible), replace the
               tool result content with "Tool Successful (N chars)"
OMIT         — remove the tool_calls entry from the assistant message AND drop the
               tool result message entirely
SHORT        — truncate the tool result to TOOL_SHORT_AMOUNT chars and append
               "... (N more chars)"

Already-stubbed results (produced by _stub_tool_result, start with the marker
below) are always treated as PARAMS_ONLY regardless of the declared policy —
showing the preview again wastes tokens.
"""
from __future__ import annotations

import copy

from src.tools._leave_out import LeaveOut, get_leave_out, get_short_amount

_STUB_MARKER = "** STUBBED LONG RETURN VALUE **"


def _is_stubbed(content: str) -> bool:
    return isinstance(content, str) and content.startswith(_STUB_MARKER)


def strip_down_messages(
    messages: list[dict],
    tool_map: dict,
    assistant_truncation_chars: int | None = None,
) -> list[dict]:
    """
    Return a deep-copied, stripped list of messages.

    tool_map: dict[tool_name: str, module] — same _TOOL_MAP used by execute_tool.

    assistant_truncation_chars controls what happens to the text content field on
    assistant messages that also have tool_calls (the "interim" narration):
      None    — leave as-is (default)
      0       — set content to None (fully omit)
      N > 0   — truncate to N chars and append '... (M more chars)'
    """
    messages = copy.deepcopy(messages)

    # --- Pass 1: collect per-tool-call-id policy ---
    tool_call_policies: dict[str, LeaveOut] = {}
    tool_call_short_amounts: dict[str, int] = {}

    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tc_id: str = tc.get("id", "")
                name: str = tc.get("function", {}).get("name", "")
                module = tool_map.get(name)
                policy = get_leave_out(module) if module is not None else LeaveOut.KEEP
                tool_call_policies[tc_id] = policy
                if policy == LeaveOut.SHORT:
                    tool_call_short_amounts[tc_id] = (
                        get_short_amount(module) if module is not None else 500
                    )

    omit_ids = {tid for tid, p in tool_call_policies.items() if p == LeaveOut.OMIT}

    # --- Pass 2: rebuild messages applying policies ---
    result: list[dict] = []

    for msg in messages:
        role = msg.get("role")

        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                # Remove omitted tool calls from assistant message
                kept_tcs = [tc for tc in tool_calls if tc.get("id", "") not in omit_ids]
                if not kept_tcs and not msg.get("content"):
                    # Nothing left in this assistant turn — drop it entirely
                    continue
                if kept_tcs:
                    msg["tool_calls"] = kept_tcs
                else:
                    msg.pop("tool_calls", None)

                # Apply assistant interim content truncation (only on messages
                # that originally had tool_calls — not pure text responses)
                if assistant_truncation_chars is not None:
                    content = msg.get("content") or ""
                    if assistant_truncation_chars == 0:
                        msg["content"] = None
                    elif content and len(content) > assistant_truncation_chars:
                        overflow = len(content) - assistant_truncation_chars
                        msg["content"] = content[:assistant_truncation_chars] + f"... ({overflow} more chars)"

            result.append(msg)

        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id in omit_ids:
                # Drop the result message entirely
                continue

            policy = tool_call_policies.get(tc_id, LeaveOut.KEEP)
            content: str = msg.get("content") or ""

            if policy == LeaveOut.PARAMS_ONLY or _is_stubbed(content):
                n = len(content)
                msg["content"] = f"Tool Successful ({n} chars)"

            elif policy == LeaveOut.SHORT:
                limit = tool_call_short_amounts.get(tc_id, 500)
                if len(content) > limit:
                    overflow = len(content) - limit
                    msg["content"] = content[:limit] + f"... ({overflow} more chars)"

            result.append(msg)

        else:
            result.append(msg)

    return result
