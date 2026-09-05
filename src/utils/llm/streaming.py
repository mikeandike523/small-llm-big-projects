from __future__ import annotations
from dataclasses import dataclass, field
import json
import logging
from numbers import Number
from typing import Callable, Optional, Any

import httpx
from termcolor import colored

from src.utils.llm.types import DialectAdapter, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class StreamResult:
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None
    stop_reason: str | None = None
    reasoning_native: dict | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class FetchResult:
    content: str
    reasoning: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None
    reasoning_native: dict | None = None

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
    _config_loader: Optional[Callable[[], Any]]
    _system_params: dict

    def __init__(
        self,
        endpoint: str,
        token: str,
        timeout_s=None,
        model=None,
        default_parameters={},
        adapter: "DialectAdapter | None" = None,
        config_loader: Optional[Callable[[], Any]] = None,
        system_params: dict = {},
    ):
        self._endpoint = endpoint
        self._token = token
        self._model = model
        self._default_parameters = default_parameters
        self._timeout_s = timeout_s
        self._config_loader = config_loader
        self._system_params = system_params

        if adapter is not None:
            self._adapter = adapter
        else:
            from src.utils.llm.dialect import OpenAICompletionsDialect

            self._adapter = OpenAICompletionsDialect()

    def _refresh(self) -> None:
        """Reload endpoint/token/model/params from config_loader if one is set."""
        if self._config_loader is None:
            return
        config = self._config_loader()
        if config is None:
            return
        from src.utils.llm.dialect import detect_dialect, get_adapter

        self._endpoint = config["endpoint_url"]
        self._token = config["token_value"]
        self._model = config.get("model")
        self._default_parameters = config.get("model_params", {})
        self._system_params = config.get("system_params", {})
        dialect = detect_dialect(
            provider=config.get("provider"),
            endpoint_url=config.get("endpoint_url"),
            model=config.get("model"),
        )
        self._adapter = get_adapter(dialect)

    def _build_base_payload(
        self, messages, max_tokens, parameters, tools, streaming: bool
    ) -> dict:
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
            from src.utils.llm.dialect import should_force_tool_strict
            from src.utils.tool_calling.strict_mode import set_tool_defs_strict

            override = self._system_params.get("override_strict_tool_def")
            decision = (
                override
                if override is not None
                else should_force_tool_strict(self._adapter.dialect_name, self._model)
            )
            if decision is not None:
                payload["tools"] = set_tool_defs_strict(payload["tools"], decision)
        return payload

    async def stream(
        self,
        messages,
        on_data: Callable[[dict], None],
        max_tokens=None,
        parameters={},
        tools: Optional[list[dict]] = None,
    ) -> StreamResult:
        """Async streaming LLM call. Cancellable via asyncio task cancellation."""
        self._refresh()
        payload = self._adapter.adapt_payload(
            self._build_base_payload(
                messages, max_tokens, parameters, tools, streaming=True
            )
        )
        headers = self._adapter.headers(self._token)
        url = self._adapter.endpoint_url(self._endpoint)
        state = self._adapter.new_stream_state()

        _pending_tool_calls: dict[int, dict] = {}
        _last_usage: dict | None = None
        _stop_reason: str | None = None

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

                    raw = line[len("data: ") :].strip()
                    if raw == "[DONE]":
                        break

                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    for event in self._adapter.parse_data(obj, state):
                        etype = event["type"]

                        if etype == "on_data":
                            chunk = {
                                "content": event.get("content"),
                                "reasoning": event.get("reasoning"),
                            }
                            on_data(chunk)

                        elif etype == "tool_delta":
                            idx = event["index"]
                            if idx not in _pending_tool_calls:
                                _pending_tool_calls[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if event.get("id"):
                                _pending_tool_calls[idx]["id"] = event["id"]
                            if event.get("name"):
                                _pending_tool_calls[idx]["name"] = event["name"]
                            if event.get("arguments"):
                                _pending_tool_calls[idx]["arguments"] += event[
                                    "arguments"
                                ]

                        elif etype == "usage":
                            _last_usage = event["usage"]

                        elif etype == "finish_reason":
                            _stop_reason = event["reason"]

        tool_calls = []
        for entry in _pending_tool_calls.values():
            try:
                arguments = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=entry["id"], name=entry["name"], arguments=arguments)
            )

        return StreamResult(
            tool_calls=tool_calls,
            usage=_last_usage,
            stop_reason=_stop_reason,
            reasoning_native=self._adapter.finalize_reasoning(state),
        )

    def fetch(
        self,
        messages,
        max_tokens=None,
        parameters={},
        tools: Optional[list[dict]] = None,
    ) -> FetchResult:
        """Synchronous (non-streaming) request — used for out-of-band calls (e.g. hang triage)."""
        self._refresh()
        payload = self._adapter.adapt_payload(
            self._build_base_payload(
                messages, max_tokens, parameters, tools, streaming=False
            )
        )
        headers = self._adapter.headers(self._token)
        url = self._adapter.endpoint_url(self._endpoint)
        timeout = httpx.Timeout(float(self._timeout_s)) if self._timeout_s else None

        with httpx.Client() as client:
            r = client.post(url, json=payload, headers=headers, timeout=timeout)

        if r.status_code != 200:
            logger.error(colored(r.text, "red"))
        r.raise_for_status()

        resp_json = r.json()
        content, reasoning, tool_calls, reasoning_native = self._adapter.parse_response(
            resp_json
        )
        return FetchResult(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            usage=self._adapter.normalize_usage(resp_json.get("usage")),
            reasoning_native=reasoning_native,
        )
