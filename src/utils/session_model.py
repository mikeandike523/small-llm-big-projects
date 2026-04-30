from __future__ import annotations

import json
import time
import uuid as _uuid_module
from dataclasses import dataclass, field
from typing import Any

CURRENT_SCHEMA_VERSION = 5


@dataclass
class ToolCallRecord:
    id: str
    name: str
    args: dict
    result: str | None = None
    was_stubbed: bool = False
    started_at: int | None = None   # ms timestamp, set just before execute_tool
    finished_at: int | None = None  # ms timestamp, set just after execute_tool


@dataclass
class LLMExchange:
    assistant_content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    is_final: bool = False
    user_continuation: str | None = None  # injected user message after this exchange

    def to_messages(self) -> list[dict]:
        """Convert this exchange to OpenAI-format message(s)."""
        msgs: list[dict] = []
        if self.tool_calls:
            # Interim assistant message with tool calls
            msgs.append({
                "role": "assistant",
                "content": self.assistant_content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                    }
                    for tc in self.tool_calls
                ],
            })
            # Tool result messages
            for tc in self.tool_calls:
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tc.result or "",
                })
        else:
            # Interim or final assistant message without tool calls
            msgs.append({"role": "assistant", "content": self.assistant_content})
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
    detailed_summary: str | None = None  # compaction string; None when no tool calls were made

    def count_tool_calls(self) -> int:
        return sum(len(ex.tool_calls) for ex in self.exchanges)


@dataclass
class Turn:
    id: str
    subturns: list[Subturn]
    todo_snapshot: list = field(default_factory=list)
    was_impossible: bool = False   # vestigial — kept for serialization compat
    impossible_reason: str | None = None  # vestigial
    was_cancelled: bool = False
    completed: bool = False
    condensed_user: str = ""
    condensed_assistant: str = ""
    task_title: str | None = None  # Short LLM-generated title, fetched at turn start

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

    def finalize(self, session_data: dict, final_content: str, had_todo_items: bool = False) -> None:
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
    pin_project_memory: bool = True
    skills_path: str | None = None
    custom_tools_path: str | None = None
    startup_tool_calls: list = field(default_factory=list)
    interim_response_as_thinking: bool = False
    record_traces: bool = False
    created_at: float = field(default_factory=time.time)


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
        "tool_calls": [tool_call_record_to_dict(tc) for tc in ex.tool_calls],
        "is_final": ex.is_final,
        "user_continuation": ex.user_continuation,
    }


def llm_exchange_from_dict(d: dict) -> LLMExchange:
    return LLMExchange(
        assistant_content=d.get("assistant_content", ""),
        reasoning=d.get("reasoning", ""),
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
    }


def subturn_from_dict(d: dict) -> Subturn:
    return Subturn(
        id=d.get("id", str(_uuid_module.uuid4())),
        user_text=d.get("user_text", ""),
        user_text_with_context=d.get("user_text_with_context", ""),
        exchanges=[llm_exchange_from_dict(ex) for ex in d.get("exchanges", [])],
        is_continuation=d.get("is_continuation", False),
        detailed_summary=d.get("detailed_summary"),
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
    }


def turn_from_dict(d: dict) -> Turn:
    if "subturns" in d:
        subturns = [subturn_from_dict(st) for st in d["subturns"]]
    else:
        # Legacy migration (schema v3): wrap flat user_text + exchanges into a single Subturn
        subturns = [Subturn(
            id=str(_uuid_module.uuid4()),
            user_text=d.get("user_text", ""),
            user_text_with_context=d.get("user_text_with_context", ""),
            exchanges=[llm_exchange_from_dict(ex) for ex in d.get("exchanges", [])],
            is_continuation=False,
        )]
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
    )


def session_to_dict(session: Session) -> dict:
    # Exclude "memory" (RedisDict), "todo_list" (ephemeral), "_report_impossible"
    # (always cleaned before save), "__pinned_project__" (re-injected each call)
    _EXCLUDED = {"memory", "todo_list", "_report_impossible", "__pinned_project__"}
    session_data_clean = {
        k: v for k, v in session.session_data.items() if k not in _EXCLUDED
    }
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "startup_done": session.startup_done,
        "completed_turns": [turn_to_dict(t) for t in session.completed_turns],
        "current_turn": turn_to_dict(session.current_turn) if session.current_turn else None,
        "session_data": session_data_clean,
        "initial_cwd": session.initial_cwd,
        "pin_project_memory": session.pin_project_memory,
        "skills_path": session.skills_path,
        "custom_tools_path": session.custom_tools_path,
        "startup_tool_calls": session.startup_tool_calls,
        "interim_response_as_thinking": session.interim_response_as_thinking,
        "record_traces": session.record_traces,
        "created_at": session.created_at,
    }


def session_from_dict(d: dict) -> Session:
    return Session(
        session_id=d.get("session_id", ""),
        schema_version=d.get("schema_version", CURRENT_SCHEMA_VERSION),
        startup_done=d.get("startup_done", False),
        completed_turns=[turn_from_dict(t) for t in d.get("completed_turns", [])],
        current_turn=turn_from_dict(d["current_turn"]) if d.get("current_turn") else None,
        session_data=d.get("session_data", {}),
        initial_cwd=d.get("initial_cwd", ""),
        pin_project_memory=d.get("pin_project_memory", True),
        skills_path=d.get("skills_path"),
        custom_tools_path=d.get("custom_tools_path"),
        startup_tool_calls=d.get("startup_tool_calls", []),
        interim_response_as_thinking=d.get("interim_response_as_thinking", False),
        record_traces=d.get("record_traces", False),
        created_at=d.get("created_at", 0.0),
    )
