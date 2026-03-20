from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

CURRENT_SCHEMA_VERSION = 3


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
    user_continuation: str | None = None  # injected user message after this exchange (e.g. unclosed-todo reprompt)

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
        # Inject continuation user message if present (unclosed-todo reprompt / final summary request)
        if self.user_continuation:
            msgs.append({"role": "user", "content": self.user_continuation})
        return msgs


@dataclass
class Turn:
    id: str
    user_text: str
    user_text_with_context: str
    exchanges: list[LLMExchange] = field(default_factory=list)
    todo_snapshot: list = field(default_factory=list)
    was_impossible: bool = False
    impossible_reason: str | None = None
    was_cancelled: bool = False
    completed: bool = False
    condensed_user: str = ""
    condensed_assistant: str = ""

    def to_messages(self) -> list[dict]:
        """
        Rebuild OpenAI-format messages list from all exchanges.
        Format: [user_msg, (assistant_with_tools, tool_results)*, final_assistant_msg]
        """
        msgs: list[dict] = [{"role": "user", "content": self.user_text_with_context}]
        for exchange in self.exchanges:
            msgs.extend(exchange.to_messages())
        return msgs

    def count_tool_calls(self) -> int:
        return sum(len(ex.tool_calls) for ex in self.exchanges)

    def finalize(self, session_data: dict, final_content: str) -> None:
        """Build condensed user/assistant strings for use as context in future turns."""
        had_tool_calls = self.count_tool_calls() > 0
        if not had_tool_calls:
            self.condensed_user = self.user_text
            self.condensed_assistant = final_content
            return

        todo_list = session_data.get("todo_list") or []
        closed = [it["text"] for it in todo_list if it.get("status") == "closed"]
        open_items = [it["text"] for it in todo_list if it.get("status") != "closed"]
        m = len(closed)
        n_tools = self.count_tool_calls()

        if self.was_impossible:
            failed_text = ", ".join(open_items) if open_items else "none"
            thoughts = self.impossible_reason or final_content or ""
            assistant = (
                f"Hi, I could not complete your request. "
                f"I called {n_tools} tools, completed {m} todo items, "
                f"and could not complete: {failed_text}. "
                f"My final thoughts: {thoughts}"
            )
        else:
            assistant = (
                f"Hi. To complete your request, I called {n_tools} tools, "
                f"completed {m} todo items, and arrived at this answer/summary: "
                f"{final_content}"
            )

        self.condensed_user = self.user_text
        self.condensed_assistant = assistant


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


def turn_to_dict(turn: Turn) -> dict:
    return {
        "id": turn.id,
        "user_text": turn.user_text,
        "user_text_with_context": turn.user_text_with_context,
        "exchanges": [llm_exchange_to_dict(ex) for ex in turn.exchanges],
        "todo_snapshot": turn.todo_snapshot,
        "was_impossible": turn.was_impossible,
        "impossible_reason": turn.impossible_reason,
        "was_cancelled": turn.was_cancelled,
        "completed": turn.completed,
        "condensed_user": turn.condensed_user,
        "condensed_assistant": turn.condensed_assistant,
    }


def turn_from_dict(d: dict) -> Turn:
    return Turn(
        id=d["id"],
        user_text=d.get("user_text", ""),
        user_text_with_context=d.get("user_text_with_context", ""),
        exchanges=[llm_exchange_from_dict(ex) for ex in d.get("exchanges", [])],
        todo_snapshot=d.get("todo_snapshot", []),
        was_impossible=d.get("was_impossible", False),
        impossible_reason=d.get("impossible_reason"),
        was_cancelled=d.get("was_cancelled", False),
        completed=d.get("completed", False),
        condensed_user=d.get("condensed_user", ""),
        condensed_assistant=d.get("condensed_assistant", ""),
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
    )
