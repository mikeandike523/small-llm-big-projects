from __future__ import annotations

import threading
import sys
import time
import asyncio
from types import SimpleNamespace

import pytest
import httpx

from src.tools import execute_tool
from src.tools._cancellable_io import (
    copy_file_cancellable,
    read_text_cancellable,
    remove_tree_cancellable,
    write_text_cancellable,
)
from src.tools._cancellation import wait_or_cancel
from src.tools._subprocess import run_command
from src.tools._async_http import request_with_cancel
from src.tools import _async_http
from src.tools import scrape_web_page
from src.tools import list_dir
from src.tools import basic_web_request
from src.utils.exceptions import ToolTimeoutError


def _cancelled_event() -> threading.Event:
    event = threading.Event()
    event.set()
    return event


def test_execute_tool_rejects_already_cancelled_turn() -> None:
    called = False

    def execute(args, session_data):
        nonlocal called
        called = True
        return "should not run"

    module = SimpleNamespace(
        DEFINITION={
            "type": "function",
            "function": {
                "name": "sample",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        execute=execute,
    )

    with pytest.raises(ToolTimeoutError, match="cancelled by user"):
        execute_tool(
            "sample",
            {},
            special_resources={"cancel_event": _cancelled_event()},
            tool_map={"sample": module},
        )
    assert called is False


def test_interruptible_wait_wakes_for_cancellation() -> None:
    event = threading.Event()
    timer = threading.Timer(0.02, event.set)
    timer.start()
    try:
        with pytest.raises(ToolTimeoutError, match="cancelled by user"):
            wait_or_cancel("sample", event, 5)
    finally:
        timer.cancel()


def test_list_dir_checks_cancel_event_before_traversal(tmp_path) -> None:
    (tmp_path / "file.txt").write_text("content", encoding="utf-8")
    with pytest.raises(ToolTimeoutError, match="cancelled by user"):
        list_dir.execute(
            {"path": str(tmp_path), "recursive": True},
            {},
            {"cancel_event": _cancelled_event()},
        )


def test_cancellable_file_helpers_preserve_normal_behavior(tmp_path) -> None:
    event = threading.Event()
    source = tmp_path / "source.txt"
    copied = tmp_path / "copied.txt"
    write_text_cancellable(
        source,
        "abc\n" * 1000,
        tool_name="test",
        cancel_event=event,
        newline="",
    )
    copy_file_cancellable(
        str(source),
        str(copied),
        tool_name="test",
        cancel_event=event,
        preserve_metadata=True,
    )
    assert read_text_cancellable(
        copied, tool_name="test", cancel_event=event, newline=""
    ) == "abc\n" * 1000


def test_recursive_remove_refuses_to_start_when_cancelled(tmp_path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    child = root / "keep.txt"
    child.write_text("keep", encoding="utf-8")

    with pytest.raises(ToolTimeoutError, match="cancelled by user"):
        remove_tree_cancellable(
            str(root),
            tool_name="remove_dir",
            cancel_event=_cancelled_event(),
        )

    assert child.exists()


def test_network_boundary_check_propagates_cancellation(monkeypatch) -> None:
    event = threading.Event()

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def request(self, **kwargs):
            event.set()
            return SimpleNamespace()

    monkeypatch.setattr(basic_web_request.httpx, "AsyncClient", Client)

    with pytest.raises(ToolTimeoutError, match="cancelled by user"):
        basic_web_request.execute(
            {"method": "GET", "url": "https://example.test"},
            {},
            {"cancel_event": event},
        )


def test_cancelled_atomic_write_preserves_existing_file(tmp_path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(ToolTimeoutError, match="cancelled by user"):
        write_text_cancellable(
            target,
            "replacement",
            tool_name="write_text_file",
            cancel_event=_cancelled_event(),
        )

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".slbp-write-*"))


def test_subprocess_cancellation_wakes_without_polling_delay() -> None:
    event = threading.Event()
    timer = threading.Timer(0.1, event.set)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(ToolTimeoutError, match="cancelled by user"):
            run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=10,
                cancel_event=event,
            )
    finally:
        timer.cancel()

    assert time.monotonic() - started < 5


def test_async_http_cancels_the_in_flight_request_task(monkeypatch) -> None:
    stop = threading.Event()
    request_was_cancelled = threading.Event()

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def request(self, **kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                request_was_cancelled.set()
                raise

    monkeypatch.setattr(_async_http.httpx, "AsyncClient", Client)
    timer = threading.Timer(0.05, stop.set)
    timer.start()
    try:
        with pytest.raises(ToolTimeoutError, match="cancelled by user"):
            request_with_cancel(
                "sample_http_tool",
                "GET",
                "https://example.test",
                cancel_event=stop,
            )
    finally:
        timer.cancel()

    assert request_was_cancelled.is_set()


def test_async_http_returns_a_fully_read_response() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    response = request_with_cancel(
        "sample_http_tool",
        "GET",
        "https://example.test",
        client_kwargs={"transport": httpx.MockTransport(handle)},
    )

    # The per-request AsyncClient has already closed; loaded response content
    # must remain available to the synchronous tool after the bridge returns.
    assert response.json() == {"ok": True}


def test_scraper_retries_use_interruptible_waits(monkeypatch) -> None:
    requests_made = []
    waits = []

    def request(*args, **kwargs):
        requests_made.append(kwargs)
        status = 503 if len(requests_made) == 1 else 200
        return httpx.Response(status, headers={"Retry-After": "0"})

    monkeypatch.setattr(scrape_web_page, "request_with_cancel", request)
    monkeypatch.setattr(
        scrape_web_page,
        "wait_or_cancel",
        lambda tool_name, cancel_event, seconds: waits.append(seconds),
    )

    response = scrape_web_page._request_with_retries(
        "https://example.test",
        headers={},
        timeout=5,
        max_retries=1,
    )

    assert response.status_code == 200
    assert len(requests_made) == 2
    assert waits == [0.0]
