from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["text"] = "hello world\nfoo bar\nbaz qux\n"

    r = execute_tool("session_memory_text_editor", {"action": "search", "key": "text", "pattern": "foo"}, env.session_data)
    cl.check("search: found match", "Searching for 'foo' returns a result containing 'foo'", "foo" in r, f"got: {r!r}")
    cl.check("search: match count reported", "Result indicates at least one match", "match" in r.lower(), f"got: {r!r}")

    r2 = execute_tool("session_memory_text_editor", {"action": "search", "key": "text", "pattern": "xyz"}, env.session_data)
    cl.check("search: no match", "Searching for 'xyz' reports no matches", "No matches" in r2, f"got: {r2!r}")

    env.session_data["memory"]["nums"] = "line 1\nline 2\n"
    r3 = execute_tool("session_memory_text_editor", {"action": "search", "key": "nums", "pattern": r"\d+"}, env.session_data)
    cl.check("search: digits found", r"Searching for \d+ finds digit matches", "match" in r3.lower(), f"got: {r3!r}")
    cl.check("search: both lines matched", "Both lines containing digits are returned", r3.count("|") >= 2, f"got: {r3!r}")
