from src.utils.llm.dialect_openai_family import OPENROUTER, OpenRouterDialect
from src.utils.llm.streaming import StreamingLLM
import src.utils.llm.streaming as streaming_mod


def test_openrouter_preserves_plain_reasoning_for_replay() -> None:
    dialect = OpenRouterDialect()
    content, reasoning, _tool_calls, native = dialect.parse_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "done",
                        "reasoning": "plain thinking",
                    }
                }
            ]
        }
    )

    assert content == "done"
    assert reasoning == "plain thinking"
    assert native == {"dialect": OPENROUTER, "data": "plain thinking"}

    payload = dialect.adapt_payload(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "done",
                    "reasoning_native": native,
                }
            ]
        }
    )

    assert payload["messages"][0]["reasoning"] == "plain thinking"
    assert "reasoning_details" not in payload["messages"][0]
    assert "reasoning_native" not in payload["messages"][0]


def test_openrouter_preserves_reasoning_details_verbatim_for_replay() -> None:
    details = [
        {
            "type": "reasoning.encrypted",
            "data": "ciphertext",
            "id": "r1",
            "format": "anthropic-claude-v1",
            "index": 0,
            "provider_extra": {"keep": True},
        }
    ]
    dialect = OpenRouterDialect()
    _content, reasoning, _tool_calls, native = dialect.parse_response(
        {"choices": [{"message": {"content": "done", "reasoning_details": details}}]}
    )

    assert reasoning == ""
    assert native == {"dialect": OPENROUTER, "data": details}

    payload = dialect.adapt_payload(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "done",
                    "reasoning_native": native,
                }
            ]
        }
    )

    assert payload["messages"][0]["reasoning_details"] == details
    assert "reasoning" not in payload["messages"][0]


def test_openrouter_stream_reasoning_details_keeps_unknown_fields() -> None:
    dialect = OpenRouterDialect()
    state = dialect.new_stream_state()
    dialect.parse_data(
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "text": "abc",
                                "index": 0,
                                "provider_extra": "x",
                            }
                        ]
                    }
                }
            ]
        },
        state,
    )

    native = dialect.finalize_reasoning(state)

    assert native == {
        "dialect": OPENROUTER,
        "data": [
            {
                "type": "reasoning.text",
                "text": "abc",
                "index": 0,
                "provider_extra": "x",
            }
        ],
    }


def test_fetch_normalizes_non_streaming_usage(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            }

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(streaming_mod.httpx, "Client", FakeClient)

    llm = StreamingLLM(
        endpoint="https://example.test/v1",
        token="token",
        model="model",
        adapter=OpenRouterDialect(),
    )
    result = llm.fetch([{"role": "user", "content": "hi"}])

    assert result.usage == {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
