from __future__ import annotations
from typing import Callable, Optional
from numbers import Number
from dataclasses import dataclass, field
import json
import time
import warnings

import httpx
from termcolor import colored


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class TraceEntry:
    """Captured input/output of a single LLM completion. Only populated when record=True."""
    request_payload: dict  # full JSON body sent to the endpoint (model, messages, tools, etc.)
    content: str
    reasoning: str
    tool_calls: list[ToolCall]
    usage: dict | None = None
    captured_at: float = field(default_factory=time.time)  # unix timestamp, set when stream() completes
    # Set by the caller (socket_handlers) after stream() returns:
    turn_id: str = ""
    exchange_idx: int = 0


@dataclass
class StreamResult:
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None
    trace: TraceEntry | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class FetchResult:
    content: str
    reasoning: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class StreamingLLM:

    _endpoint: str
    _token: str
    _model: Optional[str]
    _default_parameters: dict
    _timeout_s: Optional[Number]

    def __init__(
        self, endpoint, token, timeout_s=None, model=None, default_parameters={}
    ):
        self._endpoint = endpoint
        self._token = token
        self._model = model
        self._default_parameters = default_parameters
        self._timeout_s = timeout_s

    async def stream(self, messages, on_data: Callable[[dict], None],
                     max_tokens=None, parameters={},
                     tools: Optional[list[dict]] = None,
                     record: bool = False) -> StreamResult:
        """Async streaming LLM call. Cancellable via asyncio task cancellation."""
        payload = {
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        payload.update(self._default_parameters)
        if self._model:
            payload["model"] = self._model
        if parameters:
            payload.update(parameters)
        payload["messages"] = messages
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        headers = {"Authorization": f"Bearer {self._token}"}

        _pending_tool_calls: dict[int, dict] = {}
        _last_usage: dict | None = None
        _trace_acc: dict[str, str] | None = {"content": "", "reasoning": ""} if record else None

        if _trace_acc is not None:
            _original_on_data = on_data
            def on_data(chunk: dict) -> None:
                if chunk.get("content"):
                    _trace_acc["content"] += chunk["content"]
                if chunk.get("reasoning"):
                    _trace_acc["reasoning"] += chunk["reasoning"]
                _original_on_data(chunk)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self._endpoint.rstrip("/") + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=None,
            ) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    print(colored(body.decode("utf-8", errors="replace"), "red"))
                r.raise_for_status()

                async for line in r.aiter_lines():
                    if not line:
                        continue

                    if not line.startswith("data: "):
                        continue

                    raw = line[len("data: "):].strip()
                    if raw == "[DONE]":
                        break

                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Capture top-level usage (present in the final usage-only chunk
                    # when stream_options.include_usage is True).
                    top_usage = obj.get("usage")
                    if top_usage:
                        _last_usage = top_usage

                    choices = obj.get("choices") or []
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {}) or {}

                    # Handle tool call deltas
                    tc_deltas = delta.get("tool_calls")
                    if tc_deltas:
                        for tc_delta in tc_deltas:
                            idx = tc_delta.get("index", 0)
                            if idx not in _pending_tool_calls:
                                _pending_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc_delta.get("id"):
                                _pending_tool_calls[idx]["id"] = tc_delta["id"]
                            func = tc_delta.get("function", {})
                            if func.get("name"):
                                _pending_tool_calls[idx]["name"] = func["name"]
                            if func.get("arguments"):
                                _pending_tool_calls[idx]["arguments"] += func["arguments"]
                        continue

                    event_data = {
                        "reasoning": delta.get("reasoning"),
                        "content": delta.get("content"),
                    }

                    if all(v is None for v in event_data.values()):
                        warnings.warn(
                            colored(
                                "Warning: got event from server with no useful data.",
                                "yellow",
                            )
                        )
                        continue
                    on_data(event_data)

        tool_calls = []
        for entry in _pending_tool_calls.values():
            try:
                arguments = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=entry["id"], name=entry["name"], arguments=arguments))

        trace: TraceEntry | None = None
        if _trace_acc is not None:
            trace = TraceEntry(
                request_payload=payload,
                content=_trace_acc["content"],
                reasoning=_trace_acc["reasoning"],
                tool_calls=tool_calls,
                usage=_last_usage,
            )

        return StreamResult(tool_calls=tool_calls, usage=_last_usage, trace=trace)

    def fetch(self, messages, max_tokens=None, parameters={},
              tools: Optional[list[dict]] = None) -> FetchResult:
        """Synchronous (non-streaming) request — used for out-of-band calls (e.g. hang triage).
        Returns the full response in one shot."""
        payload = {"stream": False}
        payload.update(self._default_parameters)
        if self._model:
            payload["model"] = self._model
        if parameters:
            payload.update(parameters)
        payload["messages"] = messages
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        headers = {"Authorization": f"Bearer {self._token}"}
        timeout = httpx.Timeout(float(self._timeout_s)) if self._timeout_s else None
        with httpx.Client() as client:
            r = client.post(
                self._endpoint.rstrip("/") + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        if r.status_code != 200:
            print(colored(r.text, "red"))
        r.raise_for_status()

        obj = r.json()
        message = obj.get("choices", [{}])[0].get("message", {}) or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or ""

        tool_calls = []
        for tc in message.get("tool_calls") or []:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=arguments,
            ))

        return FetchResult(content=content, reasoning=reasoning, tool_calls=tool_calls)
