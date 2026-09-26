from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import httpx

from src.tools._cancellation import CANCELLED_HINT, check_cancelled
from src.utils.exceptions import ToolTimeoutError


_CANCEL_POLL_INTERVAL = 0.05


async def _request_async(
    tool_name: str,
    method: str,
    url: str,
    *,
    cancel_event: threading.Event | None,
    client_kwargs: dict[str, Any],
    request_kwargs: dict[str, Any],
) -> httpx.Response:
    check_cancelled(tool_name, cancel_event)
    started_at = time.monotonic()

    async with httpx.AsyncClient(**client_kwargs) as client:
        request_task = asyncio.create_task(
            client.request(method=method, url=url, **request_kwargs)
        )
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    request_task.cancel()
                    await asyncio.gather(request_task, return_exceptions=True)
                    raise ToolTimeoutError(
                        tool_name,
                        round(time.monotonic() - started_at, 3),
                        hint=CANCELLED_HINT,
                    )
                done, _ = await asyncio.wait(
                    {request_task}, timeout=_CANCEL_POLL_INTERVAL
                )
                if done:
                    break

            check_cancelled(tool_name, cancel_event)
            return await request_task
        finally:
            if not request_task.done():
                request_task.cancel()
                await asyncio.gather(request_task, return_exceptions=True)


def request_with_cancel(
    tool_name: str,
    method: str,
    url: str,
    *,
    cancel_event: threading.Event | None = None,
    client_kwargs: dict[str, Any] | None = None,
    **request_kwargs: Any,
) -> httpx.Response:
    """Run an AsyncClient request from a synchronous tool worker.

    Tool execution normally occurs inside ``asyncio.to_thread``, so this worker
    thread has no running event loop. The private loop makes HTTPX's genuine
    async task cancellation available without changing the synchronous custom
    tool interface.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "request_with_cancel must run in a synchronous tool worker, not "
            "inside an existing asyncio event loop"
        )

    return asyncio.run(
        _request_async(
            tool_name,
            method,
            url,
            cancel_event=cancel_event,
            client_kwargs=dict(client_kwargs or {}),
            request_kwargs=request_kwargs,
        )
    )
