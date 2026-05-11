from __future__ import annotations
from dataclasses import dataclass, field
import json
import logging
import time
from numbers import Number
from typing import Callable, Optional

import httpx
from termcolor import colored

from src.utils.llm.types import DialectAdapter, ToolCall

logger = logging.getLogger(__name__)

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
    _adapter: "DialectAdapter"

    def __init__(
        self,
        endpoint: str,
        token: str,
        timeout_s=None,
        model=None,
        default_parameters={},
        adapter: "DialectAdapter | None" = None,
    ):
        self._endpoint = endpoint
        self._token = token
        self._model = model
        self._default_parameters = default_parameters
        self._timeout_s = timeout_s

        if adapter is not None:
            self._adapter = adapter
        else:
            from src.utils.llm.dialect import OpenAIDialect
            self._adapter = OpenAIDialect()

    def _build_base_payload(self, messages, max_tokens, parameters, tools, streaming: bool) -> dict:
        """Assemble the OpenAI-normalized payload before dialect adaptation."""
        payload: dict = {}
        if streaming:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        else:
            payload["stream"] = False
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
        return payload

    async def stream(
        self,
        messages,
        on_data: Callable[[dict], None],
        max_tokens=None,
        parameters={},
        tools: Optional[list[dict]] = None,
        record: bool = False,
    ) -> StreamResult:
        """Async streaming LLM call. Cancellable via asyncio task cancellation."""
        payload = self._adapter.adapt_payload(
            self._build_base_payload(messages, max_tokens, parameters, tools, streaming=True)
        )
        headers = self._adapter.headers(self._token)
        url = self._adapter.endpoint_url(self._endpoint)
        state = self._adapter.new_stream_state()

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
                url,
                json=payload,
                headers=headers,
                timeout=None,
            ) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    logger.error(colored(body.decode("utf-8", errors="replace"), "red"))
                r.raise_for_status()

                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    raw = line[len("data: "):].strip()
                    if raw == "[DONE]":
                        break

                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    for event in self._adapter.parse_data(obj, state):
                        etype = event["type"]

                        if etype == "on_data":
                            chunk = {"content": event.get("content"), "reasoning": event.get("reasoning")}
                            on_data(chunk)

                        elif etype == "tool_delta":
                            idx = event["index"]
                            if idx not in _pending_tool_calls:
                                _pending_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                            if event.get("id"):
                                _pending_tool_calls[idx]["id"] = event["id"]
                            if event.get("name"):
                                _pending_tool_calls[idx]["name"] = event["name"]
                            if event.get("arguments"):
                                _pending_tool_calls[idx]["arguments"] += event["arguments"]

                        elif etype == "usage":
                            _last_usage = event["usage"]

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

    def fetch(
        self,
        messages,
        max_tokens=None,
        parameters={},
        tools: Optional[list[dict]] = None,
    ) -> FetchResult:
        """Synchronous (non-streaming) request — used for out-of-band calls (e.g. hang triage)."""
        payload = self._adapter.adapt_payload(
            self._build_base_payload(messages, max_tokens, parameters, tools, streaming=False)
        )
        headers = self._adapter.headers(self._token)
        url = self._adapter.endpoint_url(self._endpoint)
        timeout = httpx.Timeout(float(self._timeout_s)) if self._timeout_s else None

        with httpx.Client() as client:
            r = client.post(url, json=payload, headers=headers, timeout=timeout)

        if r.status_code != 200:
            logger.error(colored(r.text, "red"))
        r.raise_for_status()

        content, reasoning, tool_calls = self._adapter.parse_response(r.json())
        return FetchResult(content=content, reasoning=reasoning, tool_calls=tool_calls)
