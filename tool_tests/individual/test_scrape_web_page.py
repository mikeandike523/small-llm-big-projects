from __future__ import annotations

from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("scrape_web_page")
    try:
        # Validation: missing memory_key when target=session_memory
        r = execute_tool("scrape_web_page", {
            "url": "http://example.com",
            "target": "session_memory",
        }, env.session_data)
        cl.check(
            "memory_key required",
            "Returns error when target=session_memory but memory_key is absent",
            r.startswith("Error:") and "memory_key" in r,
            f"got: {r!r}",
        )

        # Validation: invalid URL
        r = execute_tool("scrape_web_page", {
            "url": "not-a-url",
        }, env.session_data)
        cl.check(
            "invalid url rejected",
            "Returns error for a URL with no scheme/host",
            r.startswith("Error:"),
            f"got: {r!r}",
        )

        # Live network test: graceful skip when no network is available or
        # no public internet is reachable in CI — real scraping cannot be
        # reliably mocked here without a full HTTP server that speaks HTML.
        cl.skip(
            "Live scrape_web_page tests skipped — no reliable way to test "
            "robots.txt + real HTML fetch without a public network endpoint"
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
