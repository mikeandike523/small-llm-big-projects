from __future__ import annotations

import json
import time
import uuid as _uuid_module
from dataclasses import dataclass, field
from typing import Any

from src.utils.approval_modes import APPROVAL_MODE_DEFAULT

CURRENT_SCHEMA_VERSION = 5


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
                        "content": tc.result or "",
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
    condensed_user: str = ""
    condensed_assistant: str = ""
    task_title: str | None = None  # Short LLM-generated title, fetched at turn start
    selected_skill_ids: list[str] = field(
        default_factory=list
    )  # Skills selected for first subturn; borrowed by continuations

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

    def finalize(
        self, session_data: dict, final_content: str, had_todo_items: bool = False
    ) -> None:
        """Build condensed user/assistant strings for use as context in future turns."""
        had_tool_calls = self.count_tool_calls() > 0
        first_user_text = self.subturns[0].user_text if self.subturns else ""
        if not had_tool_calls or not had_todo_items:
            self.condensed_user = first_user_text
            self.condensed_assistant = final_content
            return

        todo_list = session_data.get("todo_list") or []
        closed = [it["text"] for it in todo_list if it.get("status") == "closed"]
        open_items = [it["text"] for it in todo_list if it.get("status") != "closed"]
        n_tools = self.count_tool_calls()

        # Items were created but wiped by finalize time — nothing useful to template.
        if not todo_list:
            self.condensed_user = first_user_text
            self.condensed_assistant = final_content
            return

        closed_text = "\n".join(f"  - {t}" for t in closed) if closed else "  (none)"
        open_text = "\n".join(f"  - {t}" for t in open_items) if open_items else None

        if self.was_impossible:
            thoughts = self.impossible_reason or final_content or ""
            parts = [
                f"I could not fully complete your request after {n_tools} tool call(s).",
                f"Completed:\n{closed_text}",
            ]
            if open_text:
                parts.append(f"Left incomplete:\n{open_text}")
            parts.append(f"Final thoughts: {thoughts}")
        else:
            parts = [
                f"I completed your request using {n_tools} tool call(s).",
                f"Completed:\n{closed_text}",
            ]
            if open_text:
                parts.append(f"Left incomplete:\n{open_text}")
            parts.append(f"Final answer: {final_content}")

        self.condensed_user = first_user_text
        self.condensed_assistant = "\n".join(parts)


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
    skills_path: str | None = None
    custom_tools_path: str | None = None
    startup_tool_calls: list = field(default_factory=list)
    interim_response_as_thinking: bool = False
    created_at: float = field(default_factory=time.time)
    profile_name: str | None = None
    approval_mode: str = APPROVAL_MODE_DEFAULT


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
        "tool_calls": [tool_call_record_to_dict(tc) for tc in ex.tool_calls],
        "is_final": ex.is_final,
        "user_continuation": ex.user_continuation,
    }


def llm_exchange_from_dict(d: dict) -> LLMExchange:
    return LLMExchange(
        assistant_content=d.get("assistant_content", ""),
        reasoning=d.get("reasoning", ""),
        reasoning_native=d.get("reasoning_native"),
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
    }


def subturn_from_dict(d: dict) -> Subturn:
    return Subturn(
        id=d.get("id", str(_uuid_module.uuid4())),
        user_text=d.get("user_text", ""),
        user_text_with_context=d.get("user_text_with_context", ""),
        exchanges=[llm_exchange_from_dict(ex) for ex in d.get("exchanges", [])],
        is_continuation=d.get("is_continuation", False),
        detailed_summary=d.get("detailed_summary"),
        approval_mode=d.get("approval_mode"),
    )


def turn_to_dict(turn: Turn) -> dict:
    return {
        "id": turn.id,
        "subturns": [subturn_to_dict(st) for st in turn.subturns],
        "todo_snapshot": turn.todo_snapshot,
        "was_impossible": turn.was_impossible,
        "impossible_reason": turn.impossible_reason,
        "was_cancelled": turn.was_cancelled,
        "completed": turn.completed,
        "condensed_user": turn.condensed_user,
        "condensed_assistant": turn.condensed_assistant,
        "task_title": turn.task_title,
        "selected_skill_ids": turn.selected_skill_ids,
    }


def turn_from_dict(d: dict) -> Turn:
    if "subturns" in d:
        subturns = [subturn_from_dict(st) for st in d["subturns"]]
    else:
        # Legacy migration (schema v3): wrap flat user_text + exchanges into a single Subturn
        subturns = [
            Subturn(
                id=str(_uuid_module.uuid4()),
                user_text=d.get("user_text", ""),
                user_text_with_context=d.get("user_text_with_context", ""),
                exchanges=[llm_exchange_from_dict(ex) for ex in d.get("exchanges", [])],
                is_continuation=False,
            )
        ]
    return Turn(
        id=d["id"],
        subturns=subturns,
        todo_snapshot=d.get("todo_snapshot", []),
        was_impossible=d.get("was_impossible", False),
        impossible_reason=d.get("impossible_reason"),
        was_cancelled=d.get("was_cancelled", False),
        completed=d.get("completed", False),
        condensed_user=d.get("condensed_user", ""),
        condensed_assistant=d.get("condensed_assistant", ""),
        task_title=d.get("task_title"),
        selected_skill_ids=d.get("selected_skill_ids", []),
    )


def session_to_dict(session: Session) -> dict:
    # Exclude "memory" (a RedisDict, persisted separately) and the transient
    # "_report_impossible" flag. "todo_list" IS kept so the live working list
    # survives a warm reload, matching event-replay reconstruction.
    _EXCLUDED = {"memory", "_report_impossible"}
    session_data_clean = {
        k: v for k, v in session.session_data.items() if k not in _EXCLUDED
    }
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "startup_done": session.startup_done,
        "completed_turns": [turn_to_dict(t) for t in session.completed_turns],
        "current_turn": (
            turn_to_dict(session.current_turn) if session.current_turn else None
        ),
        "session_data": session_data_clean,
        "initial_cwd": session.initial_cwd,
        "skills_path": session.skills_path,
        "custom_tools_path": session.custom_tools_path,
        "startup_tool_calls": session.startup_tool_calls,
        "interim_response_as_thinking": session.interim_response_as_thinking,
        "created_at": session.created_at,
        "profile_name": session.profile_name,
        "approval_mode": session.approval_mode,
    }


_INTERRUPTED_TOOL_RESULT = "[Tool result unavailable - interrupted by server restart]"
_INTERRUPTED_ANSWER_MARKER = "[answer incomplete]"


def repair_incomplete_turn(session: Session) -> bool:
    """Repair an orphaned in-progress turn after a cold load (e.g. server restart).

    A session reconstructed from durable storage may carry a `current_turn` that
    was interrupted mid-flight: assistant exchanges with `tool_calls` whose
    results never came back, or a trailing assistant exchange with no content.
    Left as-is, `Turn.to_messages()` would emit an assistant `tool_calls`
    message with no matching `tool` results, which breaks the next LLM call.

    This:
      1. Fills any missing tool-call results with an interrupted-marker string so
         every tool_call stays paired with a tool message and user/assistant/tool
         ordering remains valid.
      2. Finalizes the orphaned turn: ensures a final assistant content, marks it
         cancelled, builds condensed strings (with an `[answer incomplete]`
         marker), moves it into `completed_turns`, and clears `current_turn`.

    Caller MUST gate this on the turn being orphaned (no live task owns it) — a
    genuinely active turn in the current process must not be touched.

    Returns True if a repair was performed.
    """
    turn = session.current_turn
    if turn is None:
        return False

    # 1. Pair up any dangling tool calls (defensively across all subturns).
    for subturn in turn.subturns:
        for exchange in subturn.exchanges:
            for tc in exchange.tool_calls:
                if tc.result is None:
                    tc.result = _INTERRUPTED_TOOL_RESULT

    # 2. Ensure the turn ends on an assistant message with some content.
    last_exchange = None
    for subturn in turn.subturns:
        if subturn.exchanges:
            last_exchange = subturn.exchanges[-1]
    if last_exchange is None or last_exchange.tool_calls or not (
        last_exchange.assistant_content or ""
    ).strip():
        # Either no exchanges, or the last action was a tool call / empty answer:
        # append a synthetic final response so the thread reads coherently.
        if turn.subturns:
            turn.subturns[-1].exchanges.append(
                LLMExchange(
                    assistant_content=_INTERRUPTED_ANSWER_MARKER,
                    is_final=True,
                )
            )
            final_content = _INTERRUPTED_ANSWER_MARKER
        else:
            final_content = _INTERRUPTED_ANSWER_MARKER
    else:
        final_content = f"{last_exchange.assistant_content} {_INTERRUPTED_ANSWER_MARKER}"

    turn.was_cancelled = True
    turn.completed = True
    turn.finalize(session.session_data, final_content, had_todo_items=False)
    session.completed_turns.append(turn)
    session.current_turn = None
    return True


def session_from_dict(d: dict) -> Session:
    return Session(
        session_id=d.get("session_id", ""),
        schema_version=d.get("schema_version", CURRENT_SCHEMA_VERSION),
        startup_done=d.get("startup_done", False),
        completed_turns=[turn_from_dict(t) for t in d.get("completed_turns", [])],
        current_turn=(
            turn_from_dict(d["current_turn"]) if d.get("current_turn") else None
        ),
        session_data=d.get("session_data", {}),
        initial_cwd=d.get("initial_cwd", ""),
        skills_path=d.get("skills_path"),
        custom_tools_path=d.get("custom_tools_path"),
        startup_tool_calls=d.get("startup_tool_calls", []),
        interim_response_as_thinking=d.get("interim_response_as_thinking", False),
        created_at=d.get("created_at", 0.0),
        profile_name=d.get("profile_name"),
        approval_mode=d.get("approval_mode", APPROVAL_MODE_DEFAULT),
    )
