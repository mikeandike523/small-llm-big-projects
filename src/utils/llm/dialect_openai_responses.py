"""
Real OpenAI's Responses API (/v1/responses) -- the wire protocol reasoning
models (o-series, gpt-5 family) actually need to surface reasoning content,
since Chat Completions can't (see the TODO(reasoning) note that used to sit
in dialect.py, and OpenAICompletionsDialect's docstring in
dialect_openai_family.py). Routed to by dialect.py's detect_dialect() only
for real OpenAI, based on openai_model_dialects.uses_responses_api(model);
never for OpenRouter or vLLM, which don't have this endpoint.

Wire shape differs from Chat Completions in three ways that matter here:

1. Request/response use a flat `input`/`output` item LIST, not
   `messages`/`choices`. There's no "message with a tool_calls array" the way
   Chat Completions has it -- a function call is its own top-level item
   (`{"type": "function_call", "call_id", "name", "arguments"}`), and so is
   its result on the way back (`{"type": "function_call_output", "call_id",
   "output"}`). Tool definitions are flat too: `{"type": "function", "name",
   "description", "parameters"}`, no nested "function" wrapper.

2. Reasoning is its own item type: `{"type": "reasoning", "id", "summary":
   [{"type": "summary_text", "text": ...}], "content": [{"type":
   "reasoning_text", "text": ...}], "encrypted_content": "...", "status"}`.
   `summary` is the (usually) always-present condensed reasoning; `content`
   is the fuller reasoning_text some models also return -- preferred over
   `summary` for display when present, matching the same
   full-text-else-summary preference used in dialect_openai_family.py's
   OpenRouterDialect. `encrypted_content` is what makes stateless (`store:
   false`) multi-turn tool use work at all; this dialect always requests it
   (`include: ["reasoning.encrypted_content"]`) since this app has no
   `previous_response_id` tracking and always resends full history itself.
   OpenAI's own guidance: pass reasoning items back verbatim alongside the
   function call they preceded. Unlike Anthropic's thinking blocks, this
   isn't a hard 400-on-modification requirement, so exact reasoning-to-
   function_call interleaving isn't reproduced here -- all of one exchange's
   reasoning items are placed before its function_call items (same
   simplification AnthropicDialect uses when there's no tool_calls at all).
   Revisit if a model is ever observed to actually need exact interleaving.

3. Streaming is event-typed (`response.output_item.added`,
   `response.function_call_arguments.delta`, `response.output_text.delta`,
   `response.reasoning_summary_text.delta`, `response.output_item.done`,
   `response.completed`, ...), not the `choices[0].delta` shape. Reasoning
   items are captured from `response.output_item.done`, not `.added` --
   OpenAI's own type docs warn `encrypted_content` may be incomplete while an
   item is still in progress. There's no confirmed streaming-delta event for
   the raw `content`/reasoning_text field (only for `summary`), so live
   streaming only shows summary text; the full reasoning_text (when a model
   returns one) still makes it into reasoning_native/parse_response's display
   text via the complete item captured at `.done`.

Verified against OpenAI's public API reference and the openai-python SDK's
generated type stubs (response_reasoning_item_param.py,
response_output_item_added/done_event.py, response_function_call_arguments_
delta_event.py, response_text_delta_event.py, response_completed_event.py,
response_usage.py) before writing this.
"""

from __future__ import annotations

import json

from src.utils.llm.types import DialectAdapter, ToolCall

OPENAI_RESPONSES = "openai_responses"


class OpenAIResponsesDialect(DialectAdapter):
    dialect_name = OPENAI_RESPONSES

    def endpoint_url(self, base: str) -> str:
        return base.rstrip("/") + "/responses"

    def headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def adapt_payload(self, payload: dict) -> dict:
        p = dict(payload)

        # Responses API has no stream_options; usage arrives unconditionally
        # on response.completed.
        p.pop("stream_options", None)

        if "max_tokens" in p:
            p["max_output_tokens"] = p.pop("max_tokens")

        p["input"] = _convert_messages(p.pop("messages", None) or [])

        if p.get("tools"):
            p["tools"] = _convert_tools(p["tools"])

        # This app always resends full conversation history itself (no
        # previous_response_id tracking), so server-side storage buys
        # nothing -- and reasoning items only carry a replayable
        # encrypted_content when explicitly requested under store=False.
        # Merge with anything already set via request_extra_params rather
        # than overwrite it.
        p["store"] = False
        include = set(p.get("include") or [])
        include.add("reasoning.encrypted_content")
        p["include"] = sorted(include)

        return p

    def new_stream_state(self) -> dict:
        return {
            "tool_info": {},  # output_index -> {"call_id": str, "name": str}
            "tool_arg_json": {},  # output_index -> accumulated arguments delta
            "output_items": {},  # output_index -> complete/partial output item
            "output_item_order": [],  # order of first appearance
            "reasoning_items": [],  # complete reasoning items, in order (from .done)
        }

    def parse_data(self, obj: dict, state: dict) -> list[dict]:
        events: list[dict] = []
        etype = obj.get("type")

        if etype == "response.output_item.added":
            item = obj.get("item") or {}
            idx = obj.get("output_index", 0)
            state["output_items"][idx] = dict(item)
            state["output_item_order"].append(idx)
            if item.get("type") == "function_call":
                state["tool_info"][idx] = {
                    "call_id": item.get("call_id", ""),
                    "name": item.get("name", ""),
                }
                state["tool_arg_json"][idx] = item.get("arguments") or ""
                initial_args = item.get("arguments") or ""
                events.append(
                    {
                        "type": "tool_delta",
                        "index": idx,
                        "id": item.get("call_id", ""),
                        "name": item.get("name", ""),
                        "arguments": initial_args,
                    }
                )

        elif etype == "response.function_call_arguments.delta":
            idx = obj.get("output_index", 0)
            info = state["tool_info"].get(idx, {})
            state["tool_arg_json"][idx] = state["tool_arg_json"].get(idx, "") + (
                obj.get("delta") or ""
            )
            item = state["output_items"].get(idx)
            if item is not None:
                item["arguments"] = state["tool_arg_json"][idx]
            events.append(
                {
                    "type": "tool_delta",
                    "index": idx,
                    "id": info.get("call_id", ""),
                    "name": info.get("name", ""),
                    "arguments": obj.get("delta") or "",
                }
            )

        elif etype == "response.output_text.delta":
            events.append({"type": "on_data", "content": obj.get("delta"), "reasoning": None})

        elif etype == "response.reasoning_summary_text.delta":
            events.append({"type": "on_data", "content": None, "reasoning": obj.get("delta")})

        elif etype == "response.output_item.done":
            item = obj.get("item") or {}
            idx = obj.get("output_index", 0)
            if idx not in state["output_items"]:
                state["output_item_order"].append(idx)
            state["output_items"][idx] = dict(item)
            if item.get("type") == "reasoning":
                # Use .done, not .added: encrypted_content may be incomplete
                # while the item is still in progress (per OpenAI's own type
                # docs).
                state["reasoning_items"].append(item)
            elif item.get("type") == "function_call":
                final_args = item.get("arguments") or ""
                if final_args and not state["tool_arg_json"].get(idx):
                    state["tool_arg_json"][idx] = final_args
                    events.append(
                        {
                            "type": "tool_delta",
                            "index": idx,
                            "id": item.get("call_id", ""),
                            "name": item.get("name", ""),
                            "arguments": final_args,
                        }
                    )

        elif etype == "response.completed":
            usage = (obj.get("response") or {}).get("usage")
            if usage:
                events.append({"type": "usage", "usage": self.normalize_usage(usage)})
            status = (obj.get("response") or {}).get("status")
            events.append({"type": "finish_reason", "reason": status or "completed"})

        elif etype == "response.failed":
            events.append({"type": "finish_reason", "reason": "failed"})

        return events

    def finalize_reasoning(self, state: dict) -> dict | None:
        reasoning_items = state.get("reasoning_items") or []
        output_items_store = state.get("output_items") or {}
        output_order = state.get("output_item_order") or []
        output_items = [output_items_store[i] for i in output_order if i in output_items_store]
        if not reasoning_items and not output_items:
            return None
        # reasoning_native is the exact ordered Responses output[] replay
        # payload here, not just reasoning. It can include reasoning,
        # function_call, and message items in model-produced order.
        return {
            "dialect": OPENAI_RESPONSES,
            "data": {
                "output_items": output_items,
                "reasoning_items": reasoning_items,
            },
        }

    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall], dict | None]:
        content_parts: list[str] = []
        reasoning_full = ""
        reasoning_summary = ""
        tool_calls: list[ToolCall] = []
        reasoning_items: list[dict] = []

        for item in obj.get("output") or []:
            itype = item.get("type")
            if itype == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        content_parts.append(part.get("text", ""))
            elif itype == "function_call":
                raw_args = item.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(
                    ToolCall(
                        id=item.get("call_id", ""),
                        name=item.get("name", ""),
                        arguments=arguments,
                    )
                )
            elif itype == "reasoning":
                reasoning_items.append(item)
                for c in item.get("content") or []:
                    if c.get("type") == "reasoning_text":
                        reasoning_full += c.get("text", "")
                for s in item.get("summary") or []:
                    if s.get("type") == "summary_text":
                        reasoning_summary += s.get("text", "")

        reasoning_display = reasoning_full or reasoning_summary
        output_items = [dict(item) for item in obj.get("output") or []]
        reasoning_native = (
            {
                "dialect": OPENAI_RESPONSES,
                "data": {
                    "output_items": output_items,
                    "reasoning_items": reasoning_items,
                },
            }
            if output_items or reasoning_items
            else None
        )
        return "".join(content_parts), reasoning_display, tool_calls, reasoning_native

    def normalize_usage(self, raw: dict | None) -> dict | None:
        if raw is None:
            return None
        result = dict(raw)
        if "total_tokens" not in result:
            result["total_tokens"] = result.get("input_tokens", 0) + result.get(
                "output_tokens", 0
            )
        return result


# ---------------------------------------------------------------------------
# Message and tool conversion helpers (OpenAI Chat-Completions -> Responses)
# ---------------------------------------------------------------------------


def _convert_messages(messages: list[dict]) -> list[dict]:
    """
    Convert OpenAI Chat-Completions-normalized messages into the Responses
    API's flat `input` item list.

    An assistant message tagged with a reasoning_native of dialect
    "openai_responses" has its raw reasoning items inserted first (before
    any text/function_call items from that same message) -- see the module
    docstring for why exact per-tool-call interleaving isn't reproduced. A
    mismatched or absent tag yields no items (silently dropped, e.g. after a
    provider switch, matching the other dialects' convention).
    """
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")

        if role == "assistant":
            native = msg.get("reasoning_native")
            if native and native.get("dialect") == OPENAI_RESPONSES:
                data = native.get("data")
                if isinstance(data, dict) and isinstance(data.get("output_items"), list):
                    # New-shape Responses payload: replay the exact native
                    # output[] items captured for this assistant exchange.
                    out.extend(data["output_items"])
                    continue
                if isinstance(data, list):
                    out.extend(data)

            tool_calls = msg.get("tool_calls")
            if tool_calls:
                text = msg.get("content")
                if text:
                    out.append({"role": "assistant", "content": text})
                for tc in tool_calls:
                    func = tc.get("function") or {}
                    out.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "arguments": func.get("arguments") or "{}",
                        }
                    )
            else:
                out.append({"role": "assistant", "content": msg.get("content") or ""})

        elif role == "tool":
            out.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": msg.get("content") or "",
                }
            )

        elif role in ("user", "system", "developer"):
            out.append({"role": role, "content": msg.get("content") or ""})

        # unrecognised roles skipped (matches dialect.py's Anthropic _convert_messages)

    return out


def _convert_tools(tools: list[dict]) -> list[dict]:
    """Flatten OpenAI Chat-Completions tool defs into the Responses API's flat shape."""
    result = []
    for tool in tools:
        fn = tool.get("function") or {}
        result.append(
            {
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return result
