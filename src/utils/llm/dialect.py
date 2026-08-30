"""
LLM wire-protocol dialect detection and adaptation.

A DialectAdapter encapsulates everything that differs between provider APIs:
URL path, auth headers, request payload shape, SSE event parsing, and
non-streaming response parsing. StreamingLLM accepts one via dependency
injection; factory.py detects and creates the right one.

Currently supported dialects: "openai_completions" (default), "openai_responses",
"openrouter", "vllm", "anthropic". See DialectAdapter's docstring (types.py)
for the reasoning_native tagged-union shape each dialect round-trips.

OpenAIResponsesDialect (dialect_openai_responses.py) is only reachable for
real OpenAI -- gated in detect_dialect() below on provider/endpoint actually
being OpenAI's own API, then routed per-model via
openai_model_dialects.uses_responses_api(). OpenRouter and vLLM never reach
it: OpenRouter fronts many providers' models behind one OpenAI-shaped
endpoint with its own reasoning convention (OpenRouterDialect), and vLLM-style
self-hosted servers don't have a /responses route at all regardless of what a
locally-served model happens to be named.
"""

from __future__ import annotations

import json

from src.utils.llm.dialect_openai_family import (
    OPENAI_COMPLETIONS,
    OPENROUTER,
    VLLM,
    OpenAICompletionsDialect,
    OpenRouterDialect,
    VLLMDialect,
)
from src.utils.llm.dialect_openai_responses import OPENAI_RESPONSES, OpenAIResponsesDialect
from src.utils.llm.openai_model_dialects import uses_responses_api
from src.utils.llm.types import DialectAdapter, ToolCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANTHROPIC = "anthropic"

_DEFAULT_ANTHROPIC_MAX_TOKENS = 8192
_ANTHROPIC_VERSION = "2023-06-01"

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_dialect(
    provider: str | None = None,
    endpoint_url: str | None = None,
    model: str | None = None,
) -> str:
    """
    Infer the API dialect from provider name, endpoint URL, and (for real
    OpenAI only) model name. Matching is case-insensitive on all inputs.
    Returns OPENAI_COMPLETIONS by default (real OpenAI Chat Completions and
    any unrecognized OpenAI-compatible endpoint).
    """
    ep = (endpoint_url or "").lower()
    pv = (provider or "").strip().lower()

    if "api.anthropic.com" in ep:
        return ANTHROPIC
    if pv in ("anthropic", "claude"):
        return ANTHROPIC
    if "openrouter.ai" in ep or pv == "openrouter":
        return OPENROUTER
    if pv == "vllm":
        return VLLM

    # Model-based Responses-vs-Completions routing only applies to real
    # OpenAI -- never to an unrecognized/self-hosted OpenAI-compatible
    # endpoint, which has no /responses route regardless of model name.
    is_real_openai = pv in ("openai", "gpt") or "api.openai.com" in ep
    if is_real_openai and uses_responses_api(model):
        return OPENAI_RESPONSES

    return OPENAI_COMPLETIONS


# ---------------------------------------------------------------------------
# Anthropic dialect
# ---------------------------------------------------------------------------


class AnthropicDialect(DialectAdapter):
    dialect_name = ANTHROPIC

    def endpoint_url(self, base: str) -> str:
        return base.rstrip("/") + "/messages"

    def headers(self, token: str) -> dict:
        return {
            "x-api-key": token,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

    def adapt_payload(self, payload: dict) -> dict:
        p = dict(payload)

        # Anthropic doesn't support stream_options
        p.pop("stream_options", None)

        # max_tokens is required by Anthropic
        if not p.get("max_tokens"):
            p["max_tokens"] = _DEFAULT_ANTHROPIC_MAX_TOKENS

        # Extract system prompt(s) from messages
        system_parts: list[str] = []
        remaining: list[dict] = []
        for msg in p.get("messages") or []:
            if msg.get("role") == "system":
                content = msg.get("content") or ""
                if isinstance(content, list):
                    system_parts.append(
                        " ".join(
                            b.get("text", "")
                            for b in content
                            if b.get("type") == "text"
                        )
                    )
                else:
                    system_parts.append(str(content))
            else:
                remaining.append(msg)

        if system_parts:
            p["system"] = "\n\n".join(system_parts)

        p["messages"] = _convert_messages(remaining)

        # Convert tool definitions
        if p.get("tools"):
            p["tools"] = _convert_tools(p["tools"])

        return p

    def new_stream_state(self) -> dict:
        return {
            "block_types": {},  # index -> "text" | "tool_use" | "thinking" | "redacted_thinking"
            "tool_info": {},  # index -> {"id": str, "name": str}
            "tool_arg_json": {},  # index -> accumulated partial_json
            "content_blocks": {},  # index -> raw Anthropic content block
            "content_block_order": [],  # order of first appearance
            "reasoning_blocks": {},  # index -> raw thinking/redacted_thinking block dict
            "reasoning_block_order": [],  # order of first appearance
        }

    def parse_data(self, obj: dict, state: dict) -> list[dict]:
        events: list[dict] = []
        etype = obj.get("type")

        if etype == "message_start":
            usage = (obj.get("message") or {}).get("usage")
            if usage:
                events.append({"type": "usage", "usage": self.normalize_usage(usage)})

        elif etype == "content_block_start":
            idx = obj.get("index", 0)
            block = obj.get("content_block") or {}
            btype = block.get("type", "text")
            state["block_types"][idx] = btype
            state["content_blocks"][idx] = dict(block)
            state["content_block_order"].append(idx)
            if btype == "tool_use":
                initial_input = block.get("input")
                state["tool_info"][idx] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                }
                state["tool_arg_json"][idx] = (
                    json.dumps(initial_input) if initial_input else ""
                )
                events.append(
                    {
                        "type": "tool_delta",
                        "index": idx,
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": json.dumps(initial_input) if initial_input else "",
                    }
                )
            elif btype in ("thinking", "redacted_thinking"):
                # Redacted blocks arrive fully-formed here (opaque `data`, no
                # deltas); thinking blocks start empty and fill in via
                # thinking_delta/signature_delta below. Either way, seed from
                # whatever the start event already gave us.
                state["reasoning_blocks"][idx] = dict(block)
                state["reasoning_block_order"].append(idx)

        elif etype == "content_block_delta":
            idx = obj.get("index", 0)
            delta = obj.get("delta") or {}
            dtype = delta.get("type")
            btype = state["block_types"].get(idx, "text")

            if dtype == "text_delta" and btype == "text":
                block = state["content_blocks"].get(idx)
                if block is not None:
                    block["text"] = block.get("text", "") + (delta.get("text") or "")
                events.append(
                    {"type": "on_data", "content": delta.get("text"), "reasoning": None}
                )

            elif dtype == "thinking_delta" and btype == "thinking":
                chunk = delta.get("thinking")
                events.append({"type": "on_data", "content": None, "reasoning": chunk})
                block = state["content_blocks"].get(idx)
                if block is not None:
                    block["thinking"] = block.get("thinking", "") + (chunk or "")
                acc = state["reasoning_blocks"].get(idx)
                if acc is not None:
                    acc["thinking"] = acc.get("thinking", "") + (chunk or "")

            elif dtype == "signature_delta" and btype == "thinking":
                block = state["content_blocks"].get(idx)
                if block is not None:
                    block["signature"] = delta.get("signature", "")
                acc = state["reasoning_blocks"].get(idx)
                if acc is not None:
                    acc["signature"] = delta.get("signature", "")

            elif dtype == "input_json_delta" and btype == "tool_use":
                info = state["tool_info"].get(idx, {})
                state["tool_arg_json"][idx] = state["tool_arg_json"].get(idx, "") + (
                    delta.get("partial_json", "") or ""
                )
                events.append(
                    {
                        "type": "tool_delta",
                        "index": idx,
                        "id": info.get("id", ""),
                        "name": info.get("name", ""),
                        "arguments": delta.get("partial_json", ""),
                    }
                )

        elif etype == "message_delta":
            delta = obj.get("delta") or {}
            stop_reason = delta.get("stop_reason")
            if stop_reason:
                events.append({"type": "finish_reason", "reason": stop_reason})
            usage = obj.get("usage")
            if usage:
                # merge output tokens into any existing usage event
                events.append({"type": "usage", "usage": self.normalize_usage(usage)})

        return events

    def finalize_reasoning(self, state: dict) -> dict | None:
        content_order = state.get("content_block_order") or []
        reasoning_order = state.get("reasoning_block_order") or []
        if not content_order and not reasoning_order:
            return None
        content_blocks = state.get("content_blocks") or {}
        for idx, raw_args in (state.get("tool_arg_json") or {}).items():
            block = content_blocks.get(idx)
            if block is None:
                continue
            if not raw_args and "input" in block:
                continue
            try:
                block["input"] = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                block["input"] = {}
        reasoning_blocks = state.get("reasoning_blocks") or {}
        # reasoning_native is the exact assistant content[] replay payload here,
        # not just reasoning. Anthropic can interleave thinking, tool_use, and
        # text blocks; preserving content_blocks keeps that provider order.
        return {
            "dialect": ANTHROPIC,
            "data": {
                "content_blocks": [content_blocks[i] for i in content_order],
                "reasoning_blocks": [reasoning_blocks[i] for i in reasoning_order],
            },
        }

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall], dict | None]:
        content_text = ""
        reasoning_text = ""
        tool_calls: list[ToolCall] = []
        reasoning_blocks: list[dict] = []
        for block in obj.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                content_text += block.get("text", "")
            elif btype == "thinking":
                reasoning_text += block.get("thinking", "")
                reasoning_blocks.append(block)
            elif btype == "redacted_thinking":
                reasoning_blocks.append(block)
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
        content_blocks = [dict(block) for block in obj.get("content") or []]
        reasoning_native = (
            {
                "dialect": ANTHROPIC,
                "data": {
                    "content_blocks": content_blocks,
                    "reasoning_blocks": reasoning_blocks,
                },
            }
            if content_blocks or reasoning_blocks
            else None
        )
        return content_text, reasoning_text, tool_calls, reasoning_native

    def normalize_usage(self, raw: dict | None) -> dict | None:
        if raw is None:
            return None
        result = {k: v for k, v in raw.items()}
        # Anthropic already uses input_tokens / output_tokens
        if "total_tokens" not in result:
            result["total_tokens"] = result.get("input_tokens", 0) + result.get(
                "output_tokens", 0
            )
        return result


# ---------------------------------------------------------------------------
# Message and tool conversion helpers (OpenAI → Anthropic)
# ---------------------------------------------------------------------------


def _convert_messages(messages: list[dict]) -> list[dict]:
    """
    Convert OpenAI-format messages to Anthropic format.
    Consecutive tool result messages are merged into a single user message.

    An assistant message tagged with a reasoning_native of dialect "anthropic"
    has its raw thinking/redacted_thinking blocks prepended to the content
    array, complete and unmodified, before any text/tool_use blocks -- this is
    required (not just recommended) whenever the message carries tool_calls,
    and preserving it on plain-text turns too matches Anthropic's guidance to
    pass everything back across turns. A mismatched or absent tag yields no
    blocks (silently dropped, e.g. after a provider switch).
    """
    out: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")

        if role == "assistant":
            native = msg.get("reasoning_native")
            content_blocks: list[dict] | None = None
            reasoning_blocks: list[dict] = []
            if native and native.get("dialect") == ANTHROPIC:
                data = native.get("data")
                if isinstance(data, dict):
                    if isinstance(data.get("content_blocks"), list):
                        content_blocks = list(data["content_blocks"])
                    if isinstance(data.get("reasoning_blocks"), list):
                        reasoning_blocks = list(data["reasoning_blocks"])
                elif isinstance(data, list):
                    reasoning_blocks = list(data)
            if content_blocks is not None:
                # New-shape Anthropic payload: replay the exact native
                # assistant content[] blocks captured for this exchange.
                out.append({"role": "assistant", "content": content_blocks})
                i += 1
                continue

            tool_calls = msg.get("tool_calls")
            if tool_calls:
                blocks: list[dict] = list(reasoning_blocks)
                text = msg.get("content")
                if text:
                    blocks.append({"type": "text", "text": text})
                for tc in tool_calls:
                    func = tc.get("function") or {}
                    raw_args = func.get("arguments") or "{}"
                    try:
                        input_data = json.loads(raw_args)
                    except json.JSONDecodeError:
                        input_data = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "input": input_data,
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
            elif reasoning_blocks:
                blocks = list(reasoning_blocks)
                text = msg.get("content") or ""
                if text:
                    blocks.append({"type": "text", "text": text})
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "assistant", "content": msg.get("content") or ""})
            i += 1

        elif role == "tool":
            # Collect all consecutive tool results into one user message
            results: list[dict] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tr = messages[i]
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tr.get("tool_call_id", ""),
                        "content": tr.get("content", ""),
                    }
                )
                i += 1
            out.append({"role": "user", "content": results})

        elif role == "user":
            content = msg.get("content")
            out.append({"role": "user", "content": content or ""})
            i += 1

        else:
            i += 1  # skip unrecognised roles

    return out


def _convert_tools(tools: list[dict]) -> list[dict]:
    """Convert OpenAI tool definitions to Anthropic format."""
    result = []
    for tool in tools:
        fn = tool.get("function") or {}
        result.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[DialectAdapter]] = {
    OPENAI_COMPLETIONS: OpenAICompletionsDialect,
    OPENAI_RESPONSES: OpenAIResponsesDialect,
    OPENROUTER: OpenRouterDialect,
    VLLM: VLLMDialect,
    ANTHROPIC: AnthropicDialect,
}


def get_adapter(dialect: str) -> DialectAdapter:
    """Return an adapter instance for the given dialect name."""
    cls = _ADAPTERS.get(dialect, OpenAICompletionsDialect)
    return cls()
