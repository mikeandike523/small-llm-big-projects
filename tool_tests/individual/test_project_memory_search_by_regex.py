from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("project_memory_search_by_regex")
    try:
        # set a key with searchable content
        execute_tool("project_memory_set_variable", {"key": "searchme", "value": "hello world foo"}, env.session_data)

        # search pattern that matches
        r = execute_tool("project_memory_search_by_regex", {"key": "searchme", "pattern": "foo"}, env.session_data)
        cl.check("pattern matches", "Returns matching lines when pattern is found", "foo" in r, f"got: {r!r}")

        # search pattern that does not match
        r2 = execute_tool("project_memory_search_by_regex", {"key": "searchme", "pattern": "xyz"}, env.session_data)
        cl.check("no matches", "Returns no-match message when pattern is not found", "No matches" in r2, f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
