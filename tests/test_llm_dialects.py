from src.utils.llm.dialect import ANTHROPIC, AnthropicDialect
from src.utils.llm.dialect_openai_family import OPENROUTER, OpenRouterDialect
from src.utils.llm.dialect_openai_responses import (
    OPENAI_RESPONSES,
    OpenAIResponsesDialect,
)
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


def test_anthropic_replays_exact_ordered_content_blocks() -> None:
    dialect = AnthropicDialect()
    content_blocks = [
        {"type": "thinking", "thinking": "think 1", "signature": "sig-1"},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "lookup",
            "input": {"q": "x"},
        },
        {"type": "thinking", "thinking": "think 2", "signature": "sig-2"},
        {"type": "text", "text": "done"},
    ]
    payload = dialect.adapt_payload(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "done",
                    "tool_calls": [
                        {
                            "id": "toolu_1",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"q": "x"}',
                            },
                        }
                    ],
                    "reasoning_native": {
                        "dialect": ANTHROPIC,
                        "data": {
                            "content_blocks": content_blocks,
                            "reasoning_blocks": [
                                content_blocks[0],
                                content_blocks[2],
                            ],
                        },
                    },
                },
                {
                    "role": "tool",
                    "tool_call_id": "toolu_1",
                    "content": "result",
                },
            ]
        }
    )

    assert payload["messages"][0]["content"] == content_blocks
    assert payload["messages"][1]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "result"}
    ]


def test_anthropic_stream_finalizes_exact_ordered_content_blocks() -> None:
    dialect = AnthropicDialect()
    state = dialect.new_stream_state()
    dialect.parse_data(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "think"},
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "sig"},
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "lookup"},
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":"x"}'},
        },
        state,
    )

    native = dialect.finalize_reasoning(state)

    assert native == {
        "dialect": ANTHROPIC,
        "data": {
            "content_blocks": [
                {"type": "thinking", "thinking": "think", "signature": "sig"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "lookup",
                    "input": {"q": "x"},
                },
            ],
            "reasoning_blocks": [
                {"type": "thinking", "thinking": "think", "signature": "sig"}
            ],
        },
    }


def test_openai_responses_replays_exact_ordered_output_items() -> None:
    dialect = OpenAIResponsesDialect()
    output_items = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "cipher"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"q":"x"}',
        },
        {"type": "reasoning", "id": "rs_2", "encrypted_content": "cipher2"},
    ]
    payload = dialect.adapt_payload(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": '{"q":"x"}',
                            },
                        }
                    ],
                    "reasoning_native": {
                        "dialect": OPENAI_RESPONSES,
                        "data": {
                            "output_items": output_items,
                            "reasoning_items": [output_items[0], output_items[2]],
                        },
                    },
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            ],
            "tools": [],
        }
    )

    assert payload["input"] == output_items + [
        {"type": "function_call_output", "call_id": "call_1", "output": "result"}
    ]
    assert payload["store"] is False
    assert "reasoning.encrypted_content" in payload["include"]


def test_openai_responses_stream_finalizes_exact_output_order() -> None:
    dialect = OpenAIResponsesDialect()
    state = dialect.new_stream_state()
    dialect.parse_data(
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "reasoning", "id": "rs_1"},
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "reasoning",
                "id": "rs_1",
                "encrypted_content": "cipher",
            },
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {
                "type": "function_call",
                "call_id": "call_1",
                "name": "lookup",
            },
        },
        state,
    )
    dialect.parse_data(
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 1,
            "delta": '{"q":"x"}',
        },
        state,
    )

    native = dialect.finalize_reasoning(state)

    assert native == {
        "dialect": OPENAI_RESPONSES,
        "data": {
            "output_items": [
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "cipher"},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"q":"x"}',
                },
            ],
            "reasoning_items": [
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "cipher"}
            ],
        },
    }
