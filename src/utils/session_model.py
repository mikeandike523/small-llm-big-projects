from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from src.utils.approval_modes import APPROVAL_MODE_DEFAULT

CURRENT_SCHEMA_VERSION = 6

# The result shown for a tool call that never got one (the turn was interrupted
# mid-tool). Stored data keeps result=None; see conversation_history.py.
INTERRUPTED_TOOL_RESULT = (
    "[Tool result unavailable: interrupted before the tool finished]"
)


@dataclass
class ToolCallRecord:
    id: str
    name: str
    args: dict
    result: str | None = None
    was_stubbed: bool = False
    started_at: int | None = None  # ms timestamp, set just before execute_tool
    finished_at: int | None = None  # ms timestamp, set just after execute_tool


@dataclass
class LLMExchange:
    assistant_content: str = ""
    reasoning: str = ""
    # Provider-native reasoning capture: {"dialect": str, "data": <verbatim
    # payload>}, opaque outside the dialect that produced it. See
    # DialectAdapter's docstring (utils/llm/types.py) for the full contract.
    # Historical name caveat: for ordered-output dialects this may include
    # exact native assistant text/tool-call blocks too, not just reasoning.
    reasoning_native: dict | None = None
    usage: dict | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    is_final: bool = False
    user_continuation: str | None = None  # injected user message after this exchange

    def to_messages(self) -> list[dict]:
        """Convert this exchange to OpenAI-format message(s).

        This is called only for exchanges in the current live subturn. Prior
        subturns are compacted/summarized, so their tool calls and native
        replay payloads are intentionally not resent.
        """
        msgs: list[dict] = []
        if self.tool_calls:
            # Interim assistant message with tool calls
            assistant_msg = {
                "role": "assistant",
                "content": self.assistant_content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in self.tool_calls
                ],
            }
            if self.reasoning_native is not None:
                assistant_msg["reasoning_native"] = self.reasoning_native
            msgs.append(assistant_msg)
            # Tool result messages
            for tc in self.tool_calls:
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            tc.result
                            if tc.result is not None
                            else INTERRUPTED_TOOL_RESULT
                        ),
                    }
                )
        else:
            # Interim or final assistant message without tool calls
            assistant_msg = {"role": "assistant", "content": self.assistant_content}
            if self.reasoning_native is not None:
                assistant_msg["reasoning_native"] = self.reasoning_native
            msgs.append(assistant_msg)
        # Inject continuation user message if present
        if self.user_continuation:
            msgs.append({"role": "user", "content": self.user_continuation})
        return msgs


SUBTURN_ORIGIN_USER = "user"
SUBTURN_ORIGIN_HEARTBEAT = "heartbeat"


@dataclass
class Subturn:
    id: str
    user_text: str
    user_text_with_context: str
    exchanges: list[LLMExchange] = field(default_factory=list)
    is_continuation: bool = False
    detailed_summary: str | None = (
        None  # compaction string; None when no tool calls were made
    )
    approval_mode: str | None = None
    # Who started this subturn: SUBTURN_ORIGIN_USER or SUBTURN_ORIGIN_HEARTBEAT.
    origin: str = SUBTURN_ORIGIN_USER
    # How many of `exchanges` are already in session_events. In memory only:
    # replay sets it, and session_writes advances it after each commit.
    saved_exchanges: int = field(default=0, compare=False, repr=False)

    def count_tool_calls(self) -> int:
        return sum(len(ex.tool_calls) for ex in self.exchanges)


@dataclass
class Turn:
    id: str
    subturns: list[Subturn]
    todo_snapshot: list = field(default_factory=list)
    was_impossible: bool = False  # vestigial — kept for serialization compat
    impossible_reason: str | None = None  # vestigial
    was_cancelled: bool = False
    completed: bool = False
    task_title: str | None = None  # Short LLM-generated title, fetched at turn start
    selected_skill_ids: list[str] = field(
        default_factory=list
    )  # Skills selected for first subturn; borrowed by continuations
    # Built from chat_history_cache rows (closed-subturn fields only), not from
    # events. Such a turn is sealed and must never be persisted again.
    from_cache: bool = False

    def to_messages(self) -> list[dict]:
        """Rebuild OpenAI-format messages list from all subturns in order."""
        msgs: list[dict] = []
        for subturn in self.subturns:
            msgs.append({"role": "user", "content": subturn.user_text_with_context})
            for exchange in subturn.exchanges:
                msgs.extend(exchange.to_messages())
        return msgs

    def count_tool_calls(self) -> int:
        return sum(st.count_tool_calls() for st in self.subturns)

    def count_exchanges(self) -> int:
        return sum(len(st.exchanges) for st in self.subturns)


@dataclass
class Session:
    session_id: str
    schema_version: int = CURRENT_SCHEMA_VERSION
    startup_done: bool = False
    completed_turns: list[Turn] = field(default_factory=list)
    current_turn: Turn | None = None
    session_data: dict = field(default_factory=dict)
    # Per-session context (set at creation time via slbp session new)
    initial_cwd: str = ""
    load_custom_skills_tools: bool = False
    startup_tool_calls: list = field(default_factory=list)
    interim_response_as_thinking: bool = False
    created_at: float = field(default_factory=time.time)
    profile_name: str | None = None
    approval_mode: str = APPROVAL_MODE_DEFAULT
    # session_meta.history_cache_compatible: chat_turn_index/chat_history_cache
    # are complete for this session, so saves keep them up to date.
    history_cache_compatible: bool = True
    # False for a settings-only Session (session_info.load_session_info): it
    # has no turns, so it must never be saved.
    turns_loaded: bool = True
    # todo_list_hash of the todo list last written to session_events (None =
    # the empty list). In memory only, like Subturn.saved_exchanges.
    saved_todo_hash: str | None = field(default=None, compare=False, repr=False)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def tool_call_record_to_dict(tc: ToolCallRecord) -> dict:
    return {
        "id": tc.id,
        "name": tc.name,
        "args": tc.args,
        "result": tc.result,
        "was_stubbed": tc.was_stubbed,
        "started_at": tc.started_at,
        "finished_at": tc.finished_at,
    }


def tool_call_record_from_dict(d: dict) -> ToolCallRecord:
    return ToolCallRecord(
        id=d["id"],
        name=d["name"],
        args=d.get("args", {}),
        result=d.get("result"),
        was_stubbed=d.get("was_stubbed", False),
        started_at=d.get("started_at"),
        finished_at=d.get("finished_at"),
    )


def llm_exchange_to_dict(ex: LLMExchange) -> dict:
    return {
        "assistant_content": ex.assistant_content,
        "reasoning": ex.reasoning,
        "reasoning_native": ex.reasoning_native,
        "usage": ex.usage,
        "tool_calls": [tool_call_record_to_dict(tc) for tc in ex.tool_calls],
        "is_final": ex.is_final,
        "user_continuation": ex.user_continuation,
    }


def llm_exchange_from_dict(d: dict) -> LLMExchange:
    return LLMExchange(
        assistant_content=d.get("assistant_content", ""),
        reasoning=d.get("reasoning", ""),
        reasoning_native=d.get("reasoning_native"),
        usage=d.get("usage"),
        tool_calls=[tool_call_record_from_dict(tc) for tc in d.get("tool_calls", [])],
        is_final=d.get("is_final", False),
        user_continuation=d.get("user_continuation"),
    )


def subturn_to_dict(st: Subturn) -> dict:
    return {
        "id": st.id,
        "user_text": st.user_text,
        "user_text_with_context": st.user_text_with_context,
        "exchanges": [llm_exchange_to_dict(ex) for ex in st.exchanges],
        "is_continuation": st.is_continuation,
        "detailed_summary": st.detailed_summary,
        "approval_mode": st.approval_mode,
        "origin": st.origin,
    }


def turn_to_dict(turn: Turn) -> dict:
    return {
        "id": turn.id,
        "subturns": [subturn_to_dict(st) for st in turn.subturns],
        "todo_snapshot": turn.todo_snapshot,
        "was_impossible": turn.was_impossible,
        "impossible_reason": turn.impossible_reason,
        "was_cancelled": turn.was_cancelled,
        "completed": turn.completed,
        "task_title": turn.task_title,
        "selected_skill_ids": turn.selected_skill_ids,
    }
