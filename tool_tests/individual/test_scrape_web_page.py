from __future__ import annotations

from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("scrape_web_page")
    try:
        r, _ = execute_tool(
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

        r, _ = execute_tool(
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
        r, _ = execute_tool(
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
        r, _ = execute_tool(
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

        # Inline results cut long lines at COLUMN_TRUNCATION_WIDTH by default.
        long_args = {
            "url": f"{server.base_url}/long-line",
            "check_robots": False,
            "min_delay_seconds": 0,
        }
        r, _ = execute_tool("scrape_web_page", long_args, env.session_data)
        lines = r.split("\n")
        cl.check(
            "long lines truncated by default",
            "A 1000-char line is cut to 300 chars plus a '[... 700 more chars]' marker",
            "x" * 300 + "[... 700 more chars]" in lines and "end" in lines,
            f"got line lengths: {[len(line) for line in lines]}",
        )

        r, _ = execute_tool(
            "scrape_web_page",
            {**long_args, "never_truncate_columns": True},
            env.session_data,
        )
        cl.check(
            "never_truncate_columns keeps full lines",
            "never_truncate_columns=true returns the 1000-char line in full",
            "x" * 1000 in r and "more chars]" not in r,
            f"got line lengths: {[len(line) for line in r.split(chr(10))]}",
        )

        # Session-memory writes are never truncated.
        r, _ = execute_tool(
            "scrape_web_page",
            {**long_args, "target": "session_memory", "memory_key": "long_page"},
            env.session_data,
        )
        stored = env.session_data.get("memory", {}).get("long_page", "")
        cl.check(
            "session memory not truncated",
            "Content written to session memory keeps the 1000-char line in full",
            "x" * 1000 in stored and "more chars]" not in stored,
            f"result: {r!r}; stored line lengths: {[len(line) for line in stored.split(chr(10))]}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
