from __future__ import annotations

import json
from typing import Any

import httpx

from src.utils.exceptions import ContextLimitExceededError

CONTEXT_LIMIT_KEYWORDS = (
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "maximum token",
    "context window",
    "too many tokens",
    "input is too long",
    "prompt is too long",
    "exceeds the maximum",
)


def parse_response_body(response: httpx.Response) -> Any:
    try:
        return json.loads(response.text)
    except Exception:
        return response.text


def is_context_limit_error(exc: Exception) -> bool:
    """Return True when an exception appears to be a model context-limit failure."""
    if isinstance(exc, ContextLimitExceededError):
        return True
    try:
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        response = exc.response
        if response is None or response.status_code not in (400, 413, 422):
            return False
        body = response.text.lower()
        return any(kw in body for kw in CONTEXT_LIMIT_KEYWORDS)
    except Exception:
        return False


def context_limit_log_object(exc: Exception) -> dict | None:
    """Build a frontend-log payload for the response body that triggered detection."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    response = exc.response
    if response is None:
        return None
    return {
        "context_limit_retry": True,
        "endpoint": str(exc.request.url) if exc.request is not None else None,
        "status": response.status_code,
        "response_body": parse_response_body(response),
    }
