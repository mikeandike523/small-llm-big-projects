"""
OpenAI-compatible /chat/completions dialects that disagree on reasoning shape:
real OpenAI (none), OpenRouter (reasoning/reasoning_details), and vLLM-family
self-hosted reasoning parsers (reasoning_content). Split out of dialect.py to
keep that file under the project's line-count goal. dialect.py imports the
constants and classes it needs from here; this module imports nothing back
from dialect.py, so there's no import cycle. See dialect.py for the Anthropic
dialect, detect_dialect(), and the adapter factory.
"""

from __future__ import annotations

import json

from src.utils.llm.types import DialectAdapter, ToolCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENAI_COMPLETIONS = "openai_completions"
OPENROUTER = "openrouter"
VLLM = "vllm"

# ---------------------------------------------------------------------------
# Shared OpenAI-compatible wire mechanics
# ---------------------------------------------------------------------------


def _reattach_reasoning_native(msg: dict, dialect_name: str, wire_key: str) -> dict:
    """
    Pop the normalized "reasoning_native" tag off msg and, if its dialect tag
    matches dialect_name, re-serialize its raw data onto wire_key. The
    normalized key is always dropped so it never leaks onto the wire -- a
    mismatched tag (e.g. a session that switched provider) is silently
    dropped rather than resent, since reasoning blocks are tied to the model
    that produced them.
    """
    native = msg.get("reasoning_native")
    if native is None:
        return msg
    out = {k: v for k, v in msg.items() if k != "reasoning_native"}
    if native.get("dialect") == dialect_name:
        out[wire_key] = native.get("data")
    return out


def _strip_reasoning_native(msg: dict) -> dict:
    """Drop the normalized reasoning_native tag with no re-serialization."""
    if "reasoning_native" not in msg:
        return msg
    return {k: v for k, v in msg.items() if k != "reasoning_native"}


class _OpenAICompatibleBase(DialectAdapter):
    """
    Shared wire mechanics for OpenAI-compatible /chat/completions backends
    (real OpenAI, OpenRouter, vLLM-family self-hosted servers). Subclasses
    differ only in how they read/write the reasoning field, since none of
    the three actually agree on that.
    """

    def endpoint_url(self, base: str) -> str:
        return base.rstrip("/") + "/chat/completions"

    def headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

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
            result["total_tokens"] = result.get("input_tokens", 0) + result.get(
                "output_tokens", 0
            )
        return result

    @staticmethod
    def _tool_deltas_to_events(tc_deltas: list[dict]) -> list[dict]:
        return [
            {
                "type": "tool_delta",
                "index": tc.get("index", 0),
                "id": tc.get("id") or "",
                "name": (tc.get("function") or {}).get("name") or "",
                "arguments": (tc.get("function") or {}).get("arguments") or "",
            }
            for tc in tc_deltas
        ]

    @staticmethod
    def _tool_calls_from_message(message: dict) -> list[ToolCall]:
        tool_calls = []
        for tc in message.get("tool_calls") or []:
            func = tc.get("function") or {}
            raw_args = func.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=func.get("name", ""), arguments=arguments)
            )
        return tool_calls


# ---------------------------------------------------------------------------
# Real OpenAI (Chat Completions) -- no reasoning exposure of any kind
# ---------------------------------------------------------------------------


class OpenAICompletionsDialect(_OpenAICompatibleBase):
    """
    Real OpenAI's /chat/completions endpoint. Confirmed against OpenAI's own
    reasoning guide: this endpoint returns zero reasoning content for
    reasoning models (o-series, gpt-5-reasoning) -- not even a summary, only
    a `usage.output_tokens_details.reasoning_tokens` count. Full reasoning
    (summaries, encrypted_content) is exclusive to the Responses API; see the
    module TODO in dialect.py.
    """

    def adapt_payload(self, payload: dict) -> dict:
        p = dict(payload)
        if p.get("messages"):
            p["messages"] = [_strip_reasoning_native(m) for m in p["messages"]]
        return p

    def new_stream_state(self) -> dict:
        return {}

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
            events.extend(self._tool_deltas_to_events(tc_deltas))
            return events

        content = delta.get("content")
        if content is not None:
            events.append({"type": "on_data", "content": content, "reasoning": None})

        finish_reason = choices[0].get("finish_reason")
        if finish_reason is not None:
            events.append({"type": "finish_reason", "reason": finish_reason})

        return events

    def finalize_reasoning(self, state: dict) -> dict | None:
        return None

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall], dict | None]:
        message = (obj.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or ""
        tool_calls = self._tool_calls_from_message(message)
        return content, "", tool_calls, None


# ---------------------------------------------------------------------------
# OpenRouter -- reasoning / reasoning_details
# ---------------------------------------------------------------------------


def _accumulate_reasoning_details(state: dict, details: list[dict]) -> str | None:
    """
    Merge one chunk's reasoning_details fragments into state, keyed by each
    block's own "index". Returns this chunk's incremental display text --
    reasoning.text preferred (full thinking), reasoning.summary as fallback --
    or None if this chunk carried only opaque data (reasoning.encrypted).

    OpenRouter requires reasoning_details be passed back unmodified. Streaming
    chunks are incremental, so merge by preserving every field seen on the
    block: append text-bearing fields and use last-write-wins for everything
    else, including provider-specific fields this client does not understand.
    """
    store = state["reasoning_details"]
    order = state["reasoning_details_order"]
    text_fragment = ""
    summary_fragment = ""
    for block in details:
        idx = block.get("index", 0)
        if idx not in store:
            store[idx] = {}
            order.append(idx)
        acc = store[idx]
        for key, value in block.items():
            if value is None:
                continue
            if key in ("text", "summary", "data"):
                acc[key] = acc.get(key, "") + value
                if key == "text":
                    text_fragment += value
                elif key == "summary":
                    summary_fragment += value
            else:
                acc[key] = value
    return text_fragment or summary_fragment or None


def _openrouter_reattach_reasoning_native(msg: dict) -> dict:
    """Reattach either structured reasoning_details or legacy plain reasoning.

    Unlike Anthropic/Responses, OpenRouter's replay payload is a sibling field
    on the assistant message; normal content/tool_calls still come from the
    generic LLMExchange fields.
    """
    native = msg.get("reasoning_native")
    if native is None:
        return msg
    out = {k: v for k, v in msg.items() if k != "reasoning_native"}
    if native.get("dialect") != OPENROUTER:
        return out
    data = native.get("data")
    if isinstance(data, list):
        out["reasoning_details"] = data
    elif isinstance(data, dict):
        if isinstance(data.get("reasoning_details"), list):
            out["reasoning_details"] = data["reasoning_details"]
        elif isinstance(data.get("reasoning"), str):
            out["reasoning"] = data["reasoning"]
    elif isinstance(data, str):
        out["reasoning"] = data
    return out


class OpenRouterDialect(_OpenAICompatibleBase):
    """
    OpenRouter's OpenAI-compatible endpoint, extended with a reasoning
    convention that has no equivalent in real OpenAI's API: legacy plain
    `message.reasoning` (string) and modern `message.reasoning_details[]`
    (typed blocks -- reasoning.text w/ signature, reasoning.summary,
    reasoning.encrypted w/ opaque data). For tool-calling continuations,
    OpenRouter's docs require reasoning_details be echoed back verbatim and
    in order, since it's often carrying an underlying provider's (e.g.
    Anthropic's) signature/encrypted content.

    Request-side opt-in (`reasoning: {effort|max_tokens, exclude, enabled}`)
    is a plain extra param -- already flows through today via the existing
    request_extra_params mechanism (factory.py/param_registry), no new
    plumbing needed here.
    """

    def adapt_payload(self, payload: dict) -> dict:
        p = dict(payload)
        if p.get("messages"):
            p["messages"] = [
                _openrouter_reattach_reasoning_native(m) for m in p["messages"]
            ]
        return p

    def new_stream_state(self) -> dict:
        return {
            "reasoning_details": {},
            "reasoning_details_order": [],
            "reasoning": "",
        }

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
            events.extend(self._tool_deltas_to_events(tc_deltas))
            return events

        details = delta.get("reasoning_details")
        if details:
            display_reasoning = _accumulate_reasoning_details(state, details)
        else:
            display_reasoning = delta.get("reasoning")
            if display_reasoning:
                state["reasoning"] += display_reasoning

        content = delta.get("content")
        if content is not None or display_reasoning is not None:
            events.append(
                {"type": "on_data", "content": content, "reasoning": display_reasoning}
            )

        finish_reason = choices[0].get("finish_reason")
        if finish_reason is not None:
            events.append({"type": "finish_reason", "reason": finish_reason})

        return events

    def finalize_reasoning(self, state: dict) -> dict | None:
        order = state.get("reasoning_details_order") or []
        if not order:
            reasoning = state.get("reasoning") or ""
            return {"dialect": OPENROUTER, "data": reasoning} if reasoning else None
        store = state["reasoning_details"]
        return {"dialect": OPENROUTER, "data": [store[i] for i in order]}

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall], dict | None]:
        message = (obj.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or ""
        tool_calls = self._tool_calls_from_message(message)

        details = message.get("reasoning_details")
        if details:
            reasoning_native = {"dialect": OPENROUTER, "data": details}
            reasoning = "".join(
                b.get("text", "") for b in details if b.get("type") == "reasoning.text"
            ) or "".join(
                b.get("summary", "") for b in details if b.get("type") == "reasoning.summary"
            ) or (message.get("reasoning") or "")
        else:
            reasoning = message.get("reasoning") or ""
            reasoning_native = (
                {"dialect": OPENROUTER, "data": reasoning} if reasoning else None
            )

        return content, reasoning, tool_calls, reasoning_native


# ---------------------------------------------------------------------------
# vLLM / DeepSeek-style reasoning parsers -- reasoning_content
# ---------------------------------------------------------------------------


class VLLMDialect(_OpenAICompatibleBase):
    """
    Self-hosted OpenAI-compatible servers running a reasoning parser (vLLM's
    --reasoning-parser, SGLang, and DeepSeek's own hosted API all share this
    convention): a `reasoning_content` field, distinct from OpenRouter's
    `reasoning`/`reasoning_details`. Per DeepSeek's own docs: once `tools` is
    present in the request (always true in this app's agent loop),
    reasoning_content must be echoed back on every subsequent assistant
    message or the API returns a 400; without `tools` it's optional and
    silently ignored if sent.
    """

    def adapt_payload(self, payload: dict) -> dict:
        p = dict(payload)
        if p.get("messages"):
            p["messages"] = [
                _reattach_reasoning_native(m, VLLM, "reasoning_content")
                for m in p["messages"]
            ]
        return p

    def new_stream_state(self) -> dict:
        return {"reasoning_content": ""}

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
            events.extend(self._tool_deltas_to_events(tc_deltas))
            return events

        content = delta.get("content")
        reasoning = delta.get("reasoning_content")
        if reasoning:
            state["reasoning_content"] += reasoning
        if content is not None or reasoning is not None:
            events.append({"type": "on_data", "content": content, "reasoning": reasoning})

        finish_reason = choices[0].get("finish_reason")
        if finish_reason is not None:
            events.append({"type": "finish_reason", "reason": finish_reason})

        return events

    def finalize_reasoning(self, state: dict) -> dict | None:
        text = state.get("reasoning_content") or ""
        return {"dialect": VLLM, "data": text} if text else None

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall], dict | None]:
        message = (obj.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        tool_calls = self._tool_calls_from_message(message)
        reasoning_native = {"dialect": VLLM, "data": reasoning} if reasoning else None
        return content, reasoning, tool_calls, reasoning_native
