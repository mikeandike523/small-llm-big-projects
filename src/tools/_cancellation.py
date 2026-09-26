from __future__ import annotations

import threading

from src.utils.exceptions import ToolTimeoutError


CANCELLED_HINT = "cancelled by user"


def get_cancel_event(
    special_resources: dict | None,
) -> threading.Event | None:
    """Return the turn cancellation event injected by the tool runner."""
    event = (special_resources or {}).get("cancel_event")
    return event if isinstance(event, threading.Event) else None


def check_cancelled(
    tool_name: str,
    cancel_event: threading.Event | None,
) -> None:
    """Raise the standard tool interruption error when Stop was requested."""
    if cancel_event is not None and cancel_event.is_set():
        raise ToolTimeoutError(tool_name, 0, hint=CANCELLED_HINT)


def wait_or_cancel(
    tool_name: str,
    cancel_event: threading.Event | None,
    seconds: float,
) -> None:
    """Wait without making cancellation wait for an uninterruptible sleep."""
    if seconds <= 0:
        check_cancelled(tool_name, cancel_event)
        return
    if cancel_event is None:
        # A local import keeps the common cancellation path event-driven.
        import time

        time.sleep(seconds)
        return
    if cancel_event.wait(seconds):
        raise ToolTimeoutError(tool_name, 0, hint=CANCELLED_HINT)
