"""
LLM wire-protocol dialect detection and adaptation.

A DialectAdapter encapsulates everything that differs between provider APIs:
URL path, auth headers, request payload shape, SSE event parsing, and
non-streaming response parsing. StreamingLLM accepts one via dependency
injection; factory.py detects and creates the right one.

Currently supported dialects: "openai" (default), "anthropic".
"""
from __future__ import annotations

import json

from src.utils.llm.types import DialectAdapter, ToolCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENAI = "openai"
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
    Matching is case-insensitive on both inputs. Returns OPENAI by default.
    """
    ep = (endpoint_url or "").lower()
    pv = (provider or "").strip().lower()

    if "api.anthropic.com" in ep:
        return ANTHROPIC
    if pv in ("anthropic", "claude"):
        return ANTHROPIC
    # openrouter and vllm both speak OpenAI-compatible
    # (explicit for clarity, but they'd fall through to default anyway)
    if "openrouter.ai" in ep:
        return OPENAI
    if pv == "vllm":
        return OPENAI

    return OPENAI


# ---------------------------------------------------------------------------
# OpenAI dialect
# ---------------------------------------------------------------------------

class OpenAIDialect(DialectAdapter):

    def endpoint_url(self, base: str) -> str:
        return base.rstrip("/") + "/chat/completions"

    def headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def adapt_payload(self, payload: dict) -> dict:
        return dict(payload)  # already in OpenAI format

    def new_stream_state(self) -> dict:
        return {}  # stateless — OpenAI parsing needs no cross-chunk state

    def parse_data(self, obj: dict, state: dict) -> list[dict]:
        events: list[dict] = []

        top_usage = obj.get("usage")
        if top_usage:
            events.append({"type": "usage", "usage": self.normalize_usage(top_usage)})

        choices = obj.get("choices") or []
        if not choices:
            return events

        delta = choices[0].get("delta") or {}

        tc_deltas = delta.get("tool_calls")
        if tc_deltas:
            for tc in tc_deltas:
                events.append({
                    "type": "tool_delta",
                    "index": tc.get("index", 0),
                    "id": tc.get("id") or "",
                    "name": (tc.get("function") or {}).get("name") or "",
                    "arguments": (tc.get("function") or {}).get("arguments") or "",
                })
            return events

        content = delta.get("content")
        reasoning = delta.get("reasoning")
        if content is not None or reasoning is not None:
            events.append({"type": "on_data", "content": content, "reasoning": reasoning})

        return events

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall]]:
        message = (obj.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or ""
        tool_calls = []
        for tc in message.get("tool_calls") or []:
            func = tc.get("function") or {}
            raw_args = func.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=arguments,
            ))
        return content, reasoning, tool_calls

    def normalize_usage(self, raw: dict | None) -> dict | None:
        if raw is None:
            return None
        result = {k: v for k, v in raw.items()}
        # Map OpenAI names → common names
        if "prompt_tokens" in result:
            result.setdefault("input_tokens", result.pop("prompt_tokens"))
        if "completion_tokens" in result:
            result.setdefault("output_tokens", result.pop("completion_tokens"))
        if "total_tokens" not in result:
            result["total_tokens"] = result.get("input_tokens", 0) + result.get("output_tokens", 0)
        return result


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
                    system_parts.append(" ".join(
                        b.get("text", "") for b in content if b.get("type") == "text"
                    ))
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
            "block_types": {},   # index -> "text" | "tool_use" | "thinking"
            "tool_info": {},     # index -> {"id": str, "name": str}
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

        elif etype == "content_block_delta":
            idx = obj.get("index", 0)
            delta = obj.get("delta") or {}
            dtype = delta.get("type")
            btype = state["block_types"].get(idx, "text")

            if dtype == "text_delta" and btype == "text":
                events.append({"type": "on_data", "content": delta.get("text"), "reasoning": None})

            elif dtype == "thinking_delta" and btype == "thinking":
                events.append({"type": "on_data", "content": None, "reasoning": delta.get("thinking")})

            elif dtype == "input_json_delta" and btype == "tool_use":
                info = state["tool_info"].get(idx, {})
                events.append({
                    "type": "tool_delta",
                    "index": idx,
                    "id": info.get("id", ""),
                    "name": info.get("name", ""),
                    "arguments": delta.get("partial_json", ""),
                })

        elif etype == "message_delta":
            usage = obj.get("usage")
            if usage:
                # merge output tokens into any existing usage event
                events.append({"type": "usage", "usage": self.normalize_usage(usage)})

        return events

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall]]:
        content_text = ""
        reasoning_text = ""
        tool_calls: list[ToolCall] = []
        for block in obj.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                content_text += block.get("text", "")
            elif btype == "thinking":
                reasoning_text += block.get("thinking", "")
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input") or {},
                ))
        return content_text, reasoning_text, tool_calls

    def normalize_usage(self, raw: dict | None) -> dict | None:
        if raw is None:
            return None
        result = {k: v for k, v in raw.items()}
        # Anthropic already uses input_tokens / output_tokens
        if "total_tokens" not in result:
            result["total_tokens"] = result.get("input_tokens", 0) + result.get("output_tokens", 0)
        return result


# ---------------------------------------------------------------------------
# Message and tool conversion helpers (OpenAI → Anthropic)
# ---------------------------------------------------------------------------

def _convert_messages(messages: list[dict]) -> list[dict]:
    """
    Convert OpenAI-format messages to Anthropic format.
    Consecutive tool result messages are merged into a single user message.
    """
    out: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")

        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                blocks: list[dict] = []
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
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": input_data,
                    })
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "assistant", "content": msg.get("content") or ""})
            i += 1

        elif role == "tool":
            # Collect all consecutive tool results into one user message
            results: list[dict] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tr = messages[i]
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tr.get("tool_call_id", ""),
                    "content": tr.get("content", ""),
                })
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
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[DialectAdapter]] = {
    OPENAI: OpenAIDialect,
    ANTHROPIC: AnthropicDialect,
}


def get_adapter(dialect: str) -> DialectAdapter:
    """Return an adapter instance for the given dialect name."""
    cls = _ADAPTERS.get(dialect, OpenAIDialect)
    return cls()
