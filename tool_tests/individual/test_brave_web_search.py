from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("brave_web_search")
    try:
        api_key = os.environ.get("BRAVE_API_KEY")
        if not api_key:
            cl.check("api key present", "BRAVE_API_KEY not set, skipping", True, "BRAVE_API_KEY not set, skipping")
            return cl.result()

        # API key is set: run a basic query and check the result is a non-empty string
        r = execute_tool("brave_web_search", {"query": "python programming language"}, env.session_data)
        cl.check("result is non-empty string", "Search returns a non-empty string result", isinstance(r, str) and len(r) > 0, f"got: {r!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
