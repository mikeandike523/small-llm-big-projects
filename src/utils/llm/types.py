from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


class DialectAdapter(ABC):
    """
    All methods take/return provider-agnostic types so StreamingLLM never
    needs to branch on dialect. Subclasses handle all wire-level translation.
    """

    @abstractmethod
    def endpoint_url(self, base: str) -> str:
        """Return the full request URL given the configured base endpoint."""

    @abstractmethod
    def headers(self, token: str) -> dict:
        """Return auth + required headers for this provider."""

    @abstractmethod
    def adapt_payload(self, payload: dict) -> dict:
        """
        Transform an OpenAI-normalized payload into the dialect's wire format.
        Input payload keys: stream, model, messages, max_tokens, tools, plus
        any extra params from default_parameters / per-call parameters.
        Must return a new dict; must not mutate the input.
        """

    @abstractmethod
    def new_stream_state(self) -> dict:
        """Return a fresh mutable state dict for one stream() call."""

    @abstractmethod
    def parse_data(self, obj: dict, state: dict) -> list[dict]:
        """
        Parse one SSE data object into zero or more typed event dicts.
        Mutates state as needed across calls within a single stream.

        Returned event types:
          {"type": "on_data",    "content": str|None, "reasoning": str|None}
          {"type": "tool_delta", "index": int, "id": str, "name": str, "arguments": str}
          {"type": "usage",      "usage": dict}
        """

    @abstractmethod
    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall]]:
        """Parse a non-streaming response object into (content, reasoning, tool_calls)."""

    @abstractmethod
    def normalize_usage(self, raw: dict | None) -> dict | None:
        """
        Map provider usage fields to a common shape:
          {input_tokens, output_tokens, total_tokens, ...extra}
        Returns None if raw is None.
        """
