from __future__ import annotations

import requests

_LOG_URL = "http://localhost:8080"


def log(message: str) -> None:
    """Send a log message to the logging server. Fails silently if unavailable."""
    try:
        requests.post(_LOG_URL, data=message.encode("utf-8"), timeout=1)
    except Exception:
        pass
