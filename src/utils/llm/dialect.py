"""
LLM wire-protocol dialect detection and adaptation.

A DialectAdapter encapsulates everything that differs between provider APIs:
URL path, auth headers, request payload shape, SSE event parsing, and
non-streaming response parsing. StreamingLLM accepts one via dependency
injection; factory.py detects and creates the right one.

Currently supported dialects: "openai_completions" (default), "openrouter",
"vllm", "anthropic". See DialectAdapter's docstring (types.py) for the
reasoning_native tagged-union shape each dialect round-trips.

TODO(reasoning): real OpenAI reasoning models (o-series, gpt-5-reasoning)
expose NO reasoning content at all through /chat/completions -- only through
the separate Responses API (/v1/responses), which has a different URL and a
different request/response shape entirely (input/output item arrays, not
messages/choices; encrypted_content lives on reasoning output items). Adding
that requires a new OpenAIResponsesDialect plus model-based routing (not
every OpenAI model/account has Responses access), since detect_dialect()
currently can't distinguish "wants Chat Completions" from "wants Responses"
for the same provider. Deferred; OpenAICompletionsDialect below is correct
for what /chat/completions can actually return today (nothing).
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
) -> str:
    """
    Infer the API dialect from provider name and/or endpoint URL.
    Matching is case-insensitive on both inputs. Returns OPENAI_COMPLETIONS
    by default (real OpenAI Chat Completions and any unrecognized
    OpenAI-compatible endpoint).
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

    return OPENAI_COMPLETIONS


# ---------------------------------------------------------------------------
# Anthropic dialect
# ---------------------------------------------------------------------------


class AnthropicDialect(DialectAdapter):

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
            if btype == "tool_use":
                state["tool_info"][idx] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                }
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
                events.append(
                    {"type": "on_data", "content": delta.get("text"), "reasoning": None}
                )

            elif dtype == "thinking_delta" and btype == "thinking":
                chunk = delta.get("thinking")
                events.append({"type": "on_data", "content": None, "reasoning": chunk})
                acc = state["reasoning_blocks"].get(idx)
                if acc is not None:
                    acc["thinking"] = acc.get("thinking", "") + (chunk or "")

            elif dtype == "signature_delta" and btype == "thinking":
                acc = state["reasoning_blocks"].get(idx)
                if acc is not None:
                    acc["signature"] = delta.get("signature", "")

            elif dtype == "input_json_delta" and btype == "tool_use":
                info = state["tool_info"].get(idx, {})
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
        order = state.get("reasoning_block_order") or []
        if not order:
            return None
        blocks = state["reasoning_blocks"]
        return {"dialect": ANTHROPIC, "data": [blocks[i] for i in order]}

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
        reasoning_native = (
            {"dialect": ANTHROPIC, "data": reasoning_blocks} if reasoning_blocks else None
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
            reasoning_blocks = (
                list(native["data"])
                if native and native.get("dialect") == ANTHROPIC
                else []
            )
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
    OPENROUTER: OpenRouterDialect,
    VLLM: VLLMDialect,
    ANTHROPIC: AnthropicDialect,
}


def get_adapter(dialect: str) -> DialectAdapter:
    """Return an adapter instance for the given dialect name."""
    cls = _ADAPTERS.get(dialect, OpenAICompletionsDialect)
    return cls()
