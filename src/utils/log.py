from __future__ import annotations

import os

import requests

_LOG_URL = f"http://localhost:{os.environ.get('LOGGING_PORT', '8080')}"


def log(message: str) -> None:
    """Send a log message to the logging server. Fails silently if unavailable."""
    try:
        requests.post(_LOG_URL, data=message.encode("utf-8"), timeout=1)
    except Exception:
        pass
