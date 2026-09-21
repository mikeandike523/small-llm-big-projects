import asyncio

import httpx
import pytest

from src.ui_connector.socket_handler_components import llm
from src.utils import session_events
from src.utils.exceptions import ContextReductionExhaustedError
from src.utils.session_model import (
    LLMExchange,
    Session,
    Subturn,
    ToolCallRecord,
    Turn,
    llm_exchange_from_dict,
    llm_exchange_to_dict,
)


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


def _rate_limit_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(
        429,
        request=request,
        json={"error": {"message": "rate limited"}},
    )
    return httpx.HTTPStatusError("rate limited", request=request, response=response)


def test_exchange_usage_round_trips_through_dict() -> None:
    exchange = LLMExchange(
        assistant_content="done",
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        is_final=True,
    )

    restored = llm_exchange_from_dict(llm_exchange_to_dict(exchange))

    assert restored.usage == exchange.usage


def test_exchange_usage_round_trips_through_event_replay() -> None:
    exchange = LLMExchange(
        assistant_content="done",
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        is_final=True,
    )
    rows = [
        {"event_type": session_events.EVT_TURN_STARTED, "payload": {"turn_id": "t1"}},
        {
            "event_type": session_events.EVT_SUBTURN_STARTED,
            "payload": {
                "turn_id": "t1",
                "subturn_id": "st1",
                "user_text": "hi",
                "user_text_with_context": "hi",
            },
        },
        {
            "event_type": session_events.EVT_EXCHANGE_RECORDED,
            "payload": {
                "subturn_id": "st1",
                "index": 0,
                "exchange": session_events.exchange_payload(exchange),
            },
        },
    ]

    restored = session_events.replay_events("s1", rows)

    assert restored.current_turn.subturns[0].exchanges[0].usage == exchange.usage


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
                exchanges=[
                    LLMExchange(assistant_content="second answer", is_final=True)
                ],
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
                exchanges=[
                    LLMExchange(assistant_content="second answer", is_final=True)
                ],
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
    monkeypatch.setattr(llm, "_get_known_max_context", lambda _profile: None)
    monkeypatch.setattr(llm, "_emit_backend_log", lambda *args, **kwargs: None)
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn(
                "st1",
                "first",
                summary="summary one",
                exchanges=[
                    LLMExchange(assistant_content="first answer", is_final=True)
                ],
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
    monkeypatch.setattr(llm, "_get_known_max_context", lambda _profile: None)
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


def test_context_retry_raises_distinct_error_after_all_subturns_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    monkeypatch.setattr(llm, "_get_known_max_context", lambda _profile: None)
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


def test_precut_starts_at_zero_without_known_max_context() -> None:
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn(
                "st1",
                "first",
                exchanges=[LLMExchange(usage={"total_tokens": 100})],
            ),
            _subturn("st2", "second"),
        ],
    )

    assert llm._initial_closed_subturn_count(current_turn, None) == 0


def test_precut_starts_at_zero_when_any_prior_hint_is_missing() -> None:
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn(
                "st1",
                "first",
                exchanges=[LLMExchange(usage={"total_tokens": 100})],
            ),
            _subturn("st2", "second", exchanges=[LLMExchange()]),
            _subturn("st3", "third"),
        ],
    )

    assert llm._initial_closed_subturn_count(current_turn, 1000) == 0


def test_precut_closes_oldest_prefix_over_context_fraction() -> None:
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn(
                "st1",
                "first",
                exchanges=[LLMExchange(usage={"total_tokens": 20})],
            ),
            _subturn(
                "st2",
                "second",
                exchanges=[LLMExchange(usage={"total_tokens": 30})],
            ),
            _subturn(
                "st3",
                "third",
                exchanges=[LLMExchange(usage={"total_tokens": 20})],
            ),
            _subturn("st4", "fourth"),
        ],
    )

    assert llm._initial_closed_subturn_count(current_turn, 80) == 1


def test_rate_limit_retries_same_payload_without_closing(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    monkeypatch.setattr(llm, "_get_known_max_context", lambda _profile: None)
    monkeypatch.setattr(llm, "_emit_backend_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm, "_rate_limit_sleep_s", lambda _idx: 0)
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn("st1", "first", summary="summary one"),
            _subturn("st2", "second"),
        ],
    )
    attempts: list[list[dict]] = []

    async def fake_call(_streaming_llm, payload, **_kwargs):
        attempts.append(payload)
        if len(attempts) == 1:
            raise _rate_limit_error()
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
    assert attempts[0] == attempts[1]
    assert not any(
        "Context Notes:" in (msg.get("content") or "") for msg in attempts[1]
    )


def test_exhausted_rate_limit_retries_raise_original_429(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_get_session_system_prompt", lambda _sid: "system")
    monkeypatch.setattr(llm, "_get_known_max_context", lambda _profile: None)
    monkeypatch.setattr(llm, "_emit_backend_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm, "_rate_limit_sleep_s", lambda _idx: 0)
    session = Session(session_id="s1")
    current_turn = Turn(
        id="t1",
        subturns=[
            _subturn("st1", "first", summary="summary one"),
            _subturn("st2", "second"),
        ],
    )
    attempts = 0
    err = _rate_limit_error()

    async def fake_call(_streaming_llm, _payload, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise err

    monkeypatch.setattr(llm, "_async_run_llm_call", fake_call)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
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

    assert exc_info.value is err
    assert attempts == llm.RATE_LIMIT_MAX_RETRIES + 1
