from __future__ import annotations

from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("scrape_web_page")
    try:
        r = execute_tool(
            "scrape_web_page",
            {
                "url": "http://example.com",
                "target": "session_memory",
            },
            env.session_data,
        )
        cl.check(
            "memory_key required",
            "Returns error when target=session_memory but memory_key is absent",
            r.startswith("Error:") and "memory_key" in r,
            f"got: {r!r}",
        )

        r = execute_tool(
            "scrape_web_page",
            {
                "url": "not-a-url",
            },
            env.session_data,
        )
        cl.check(
            "invalid url rejected",
            "Returns error for a URL with no scheme/host",
            r.startswith("Error:"),
            f"got: {r!r}",
        )

        if server is None:
            cl.skip("No MicroServer provided for scrape_web_page extraction checks")
            return cl.result()

        # Default format is 'raw' — returns the original response body.
        r = execute_tool(
            "scrape_web_page",
            {
                "url": f"{server.base_url}/article",
                "check_robots": False,
                "min_delay_seconds": 0,
            },
            env.session_data,
        )
        cl.check(
            "default format status",
            "Default scrape result includes HTTP status line",
            r.startswith("HTTP 200"),
            f"got: {r!r}",
        )
        cl.check(
            "default format is raw html",
            "Default (raw) format returns the original response body with wrapper tags",
            "<main>" in r and "<html>" in r,
            f"got: {r!r}",
        )

        # Explicit xml format extracts readable content and strips wrapper tags.
        r = execute_tool(
            "scrape_web_page",
            {
                "url": f"{server.base_url}/article",
                "check_robots": False,
                "min_delay_seconds": 0,
                "format": "xml",
            },
            env.session_data,
        )
        cl.check(
            "xml format readable",
            "xml format extracts readable article content",
            "Example Article" in r and "exercise readable extraction" in r,
            f"got: {r!r}",
        )
        cl.check(
            "xml format strips raw html",
            "xml format should not contain raw <html> or <body> wrapper tags",
            "<html>" not in r and "<body>" not in r,
            f"got: {r!r}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
