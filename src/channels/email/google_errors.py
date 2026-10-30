"""Detailed, secret-conscious Google API error reporting."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SECRET_PATTERNS = (
    re.compile(
        r'("(?:access_token|id_token|refresh_token|private_key)"\s*:\s*")[^"]+',
        re.IGNORECASE,
    ),
    re.compile(r"(Authorization\s*:\s*Bearer\s+)[^\s]+", re.IGNORECASE),
)


def redact_google_text(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(r"\1[REDACTED]", result)
    return result


def google_error_text(exc: BaseException) -> str:
    content = getattr(exc, "content", None)
    if isinstance(content, bytes):
        body = content.decode("utf-8", errors="replace")
    elif content is not None:
        body = str(content)
    else:
        body = str(exc)
    return redact_google_text(body)


def log_google_error(
    operation: str,
    exc: BaseException,
    *,
    mailbox: str,
    context: dict[str, Any] | None = None,
) -> None:
    response = getattr(exc, "resp", None)
    raw_headers = dict(response) if response is not None else {}
    allowed = {
        "content-type",
        "date",
        "server",
        "x-google-request-id",
        "x-guploader-uploadid",
    }
    headers = {k: v for k, v in raw_headers.items() if k.lower() in allowed}
    logger.error(
        "Google API request failed\n"
        "operation=%s\nmailbox=%s\nstatus=%s\nreason=%s\nuri=%s\n"
        "response_headers=%s\nresponse_body=%s\ncontext=%s",
        operation,
        mailbox,
        getattr(response, "status", None),
        getattr(exc, "reason", None),
        getattr(exc, "uri", None),
        headers,
        google_error_text(exc),
        json.dumps(context or {}, default=str, sort_keys=True),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
