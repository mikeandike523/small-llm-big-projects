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

    reasoning_native shape (returned by parse_response/finalize_reasoning, and
    read back by adapt_payload off each message before it hits the wire):

        {"dialect": <this adapter's dialect name>, "data": <verbatim provider payload>}

    "data" is opaque outside the adapter that produced it — never inspected or
    modified by session storage or other dialects. A dialect whose name doesn't
    match the tag on a message must drop reasoning_native silently rather than
    try to interpret it (this happens e.g. when a session switches provider
    mid-conversation).
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
        Mutates state as needed across calls within a single stream, including
        whatever bookkeeping finalize_reasoning() will need at stream end.

        Returned event types:
          {"type": "on_data",    "content": str|None, "reasoning": str|None}
          {"type": "tool_delta", "index": int, "id": str, "name": str, "arguments": str}
          {"type": "usage",      "usage": dict}
        """

    @abstractmethod
    def finalize_reasoning(self, state: dict) -> dict | None:
        """
        Assemble the accumulated raw reasoning blocks from one completed stream
        into a reasoning_native dict (see class docstring), or None if no
        structured reasoning was captured. Called once after the SSE loop ends.
        """

    @abstractmethod
    def parse_response(self, obj: dict) -> tuple[str, str, list[ToolCall], dict | None]:
        """
        Parse a non-streaming response object into
        (content, reasoning, tool_calls, reasoning_native).
        """

    @abstractmethod
    def normalize_usage(self, raw: dict | None) -> dict | None:
        """
        Map provider usage fields to a common shape:
          {input_tokens, output_tokens, total_tokens, ...extra}
        Returns None if raw is None.
        """
