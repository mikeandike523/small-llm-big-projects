from typing import Callable, Optional
from numbers import Number
import json
import warnings

import requests
from termcolor import colored


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

    def stream(self, messages, on_data: Callable[dict], max_tokens=None, parameters={}):
        payload = {}
        payload.update(self._default_parameters)
        if self._model:
            payload["model"] = self._model
        if parameters:
            payload.update(parameters)
        payload["messages"] = messages
        payload["max_tokens"] = max_tokens

        headers = {"Authorization": f"Bearer {self._token}"}

        with requests.post(
            self._endpoint, json=payload, stream=True, timeout=60, headers=headers
        ) as r:
            r.raise_for_status()

            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue

                # SSE lines usually look like: "data: {...}" or "data: [DONE]"
                if not line.startswith("data: "):
                    continue

                data = line[len("data: ") :].strip()
                if data == "[DONE]":
                    break

                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = obj.get("choices", [{}])[0]
                delta = choice.get("delta", {}) or {}

                data = {
                    "reasoning": delta.get("reasoning"),
                    "content": delta.get("content"),
                }

                if all(v is None for v in data.values()):
                    warnings.warn(
                        colored(
                            """\
Warning: got event from server with no useful data.
""".srtrip(),
                            "yellow",
                        )
                    )
                on_data(data)
