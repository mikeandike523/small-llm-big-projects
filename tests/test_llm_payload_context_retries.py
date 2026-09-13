import asyncio

import httpx
import pytest

from src.ui_connector.socket_handler_components import llm
from src.utils.exceptions import ContextReductionExhaustedError
from src.utils.session_model import LLMExchange, Session, Subturn, ToolCallRecord, Turn


def _subturn(
    subturn_id: str,
    user_text: str,
    *,
    summary: str | None = None,
    exchanges: list[LLMExchange] | None = None,
) -> Subturn:
    return Subturn(
        id=subturn_id,
        user_text=user_text,
        user_text_with_context=user_text,
        exchanges=exchanges or [],
        detailed_summary=summary,
    )


def _context_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "maximum context length exceeded"}},
    )
    return httpx.HTTPStatusError("bad request", request=request, response=response)


def _ordinary_400() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "invalid tool schema"}},
    )
    return httpx.HTTPStatusError("bad request", request=request, response=response)


def test_payload_can_keep_prior_current_turn_subturns_live(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    session = Session(session_id="s1")
    tool_exchange = LLMExchange(
        assistant_content="calling tool",
        reasoning_native={"dialect": "test", "data": [{"type": "reasoning"}]},
        tool_calls=[
            ToolCallRecord(
                id="call_1",
                name="lookup",
                args={"q": "thing"},
                result="tool result",
            )
        ],
    )
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn("st1", "first", summary="summary one", exchanges=[tool_exchange]),
            _subturn(
                "st2",
                "second",
                summary="summary two",
                exchanges=[LLMExchange(assistant_content="second answer", is_final=True)],
            ),
            _subturn("st3", "third"),
        ],
    )

    messages = llm._build_llm_payload(
        session,
        current_turn,
        closed_current_turn_prior_subturns=0,
    )

    assert any(
        msg.get("role") == "tool" and msg["content"] == "tool result"
        for msg in messages
    )
    assert any(
        msg.get("reasoning_native") == tool_exchange.reasoning_native
        for msg in messages
    )
    assert not any("Context Notes:" in (msg.get("content") or "") for msg in messages)


def test_payload_closes_earliest_prior_current_turn_subturns(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn(
                "st1",
                "first",
                summary="summary one",
                exchanges=[
                    LLMExchange(
                        assistant_content="first answer",
                        tool_calls=[
                            ToolCallRecord(
                                id="call_1",
                                name="lookup",
                                args={},
                                result="tool result",
                            )
                        ],
                        is_final=True,
                    )
                ],
            ),
            _subturn(
                "st2",
                "second",
                summary="summary two",
                exchanges=[LLMExchange(assistant_content="second answer", is_final=True)],
            ),
            _subturn("st3", "third"),
        ],
    )

    messages = llm._build_llm_payload(
        session,
        current_turn,
        closed_current_turn_prior_subturns=1,
    )

    assistant_texts = [
        msg.get("content") or "" for msg in messages if msg.get("role") == "assistant"
    ]
    assert "first answer\n\nContext Notes:\nsummary one" in assistant_texts
    assert "second answer" in assistant_texts
    assert not any(msg.get("role") == "tool" for msg in messages)


def test_context_retry_closes_one_more_prior_subturn(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    monkeypatch.setattr(llm, "_emit_backend_log", lambda *args, **kwargs: None)
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn(
                "st1",
                "first",
                summary="summary one",
                exchanges=[LLMExchange(assistant_content="first answer", is_final=True)],
            ),
            _subturn("st2", "second"),
        ],
    )
    attempts: list[list[dict]] = []

    async def fake_call(_streaming_llm, payload, **_kwargs):
        attempts.append(payload)
        if len(attempts) == 1:
            raise _context_error()
        return object(), "ok", ""

    monkeypatch.setattr(llm, "_async_run_llm_call", fake_call)

    result = asyncio.run(
        llm._async_run_llm_call_with_context_retries(
            object(),
            session,
            current_turn,
            None,
            session_id="s1",
            turn_id="t1",
            subturn_id="st2",
            exchange_idx=0,
        )
    )

    assert result[1] == "ok"
    assert len(attempts) == 2
    assert not any(
        "Context Notes:" in (msg.get("content") or "") for msg in attempts[0]
    )
    assert any(
        "Context Notes:\nsummary one" in (msg.get("content") or "")
        for msg in attempts[1]
    )


def test_context_retry_fails_fast_on_non_context_error(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn("st1", "first", summary="summary one"),
            _subturn("st2", "second"),
        ],
    )
    attempts = 0

    async def fake_call(_streaming_llm, _payload, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise _ordinary_400()

    monkeypatch.setattr(llm, "_async_run_llm_call", fake_call)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            llm._async_run_llm_call_with_context_retries(
                object(),
                session,
                current_turn,
                None,
                session_id="s1",
                turn_id="t1",
                subturn_id="st2",
                exchange_idx=0,
            )
        )

    assert attempts == 1


def test_context_retry_raises_distinct_error_after_all_subturns_closed(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    monkeypatch.setattr(llm, "_emit_backend_log", lambda *args, **kwargs: None)
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn("st1", "first", summary="summary one"),
            _subturn("st2", "second"),
        ],
    )
    attempts = 0

    async def fake_call(_streaming_llm, _payload, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise _context_error()

    monkeypatch.setattr(llm, "_async_run_llm_call", fake_call)

    with pytest.raises(ContextReductionExhaustedError) as exc_info:
        asyncio.run(
            llm._async_run_llm_call_with_context_retries(
                object(),
                session,
                current_turn,
                None,
                session_id="s1",
                turn_id="t1",
                subturn_id="st2",
                exchange_idx=0,
            )
        )

    assert attempts == 2
    assert "Could not make request, context exceeded" in str(exc_info.value)
