from __future__ import annotations

import threading
import time

from src.tools import check_needs_approval, execute_tool
from src.utils.exceptions import ToolTimeoutError
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("sleep")
    try:
        started = time.monotonic()
        result, _ = execute_tool("sleep", {"seconds": 0.2}, env.session_data)
        elapsed = time.monotonic() - started
        cl.check(
            "waits",
            "Waits for about the requested time and reports it",
            0.15 <= elapsed < 5 and "0.2" in result,
            f"elapsed={elapsed} result={result!r}",
        )

        needs, _ = check_needs_approval("sleep", {"seconds": 1})
        cl.check("no approval", "Never needs approval", needs is False, f"{needs!r}")

        result, _ = execute_tool("sleep", {"seconds": 301}, env.session_data)
        cl.check(
            "maximum",
            "Refuses more than 300 seconds",
            "301" in result or "maximum" in result.lower(),
            f"got: {result!r}",
        )

        cancel_event = threading.Event()
        threading.Timer(0.1, cancel_event.set).start()
        started = time.monotonic()
        cancelled = False
        try:
            execute_tool(
                "sleep",
                {"seconds": 60},
                env.session_data,
                {"cancel_event": cancel_event},
            )
        except ToolTimeoutError:
            cancelled = True
        elapsed = time.monotonic() - started
        cl.check(
            "stop wakes it",
            "The turn's cancel event ends the wait immediately",
            cancelled and elapsed < 5,
            f"cancelled={cancelled} elapsed={elapsed}",
        )
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
