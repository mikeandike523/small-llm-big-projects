from __future__ import annotations
from typing import Callable, Optional
from numbers import Number
from dataclasses import dataclass, field
import json
import warnings

import requests
from termcolor import colored


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class StreamResult:
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

    def stream(self, messages, on_data: Callable[[dict], None],
               max_tokens=None, parameters={},
               tools: Optional[list[dict]] = None) -> StreamResult:
        payload = {
            "stream":True
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

        with requests.post(
            self._endpoint.rstrip("/") + "/chat/completions", json=payload, stream=True, timeout=60, headers=headers
        ) as r:
            
            if r.status_code!=200:
                print(colored(r.text,"red"))
                

            r.raise_for_status()

            _pending_tool_calls: dict[int, dict] = {}

            for line in r.iter_lines(decode_unicode=True):

                if not line:
                    continue

                # SSE lines usually look like: "data: {...}" or "data: [DONE]"
                if not line.startswith("data: "):
                    continue

                raw = line[len("data: "):].strip()
                if raw == "[DONE]":
                    break

                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                choice = obj.get("choices", [{}])[0]
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

        return StreamResult(tool_calls=tool_calls)
