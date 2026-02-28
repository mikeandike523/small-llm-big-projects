from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_search_by_regex")
    try:
        env.session_data["memory"]["text"] = "hello world\nfoo bar\nbaz qux\n"

        # pattern that matches
        r = execute_tool("session_memory_search_by_regex", {"key": "text", "pattern": "foo"}, env.session_data)
        cl.check("found match", "Searching for 'foo' returns a result containing 'foo'", "foo" in r, f"got: {r!r}")
        cl.check("match count reported", "Result indicates at least one match", "match" in r.lower(), f"got: {r!r}")

        # pattern with no matches
        r2 = execute_tool("session_memory_search_by_regex", {"key": "text", "pattern": "xyz"}, env.session_data)
        cl.check("no match", "Searching for 'xyz' reports no matches", "No matches" in r2, f"got: {r2!r}")

        # digits pattern against numeric content
        env.session_data["memory"]["nums"] = "line 1\nline 2\n"
        r3 = execute_tool("session_memory_search_by_regex", {"key": "nums", "pattern": r"\d+"}, env.session_data)
        cl.check("digits found", r"Searching for \d+ finds digit matches", "match" in r3.lower(), f"got: {r3!r}")
        cl.check("both lines matched", "Both lines containing digits are returned", r3.count("|") >= 2, f"got: {r3!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
