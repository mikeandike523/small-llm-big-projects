from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("project_memory_list_variables")
    try:
        # set two keys
        execute_tool("project_memory_set_variable", {"key": "list.alpha", "value": "1"}, env.session_data)
        execute_tool("project_memory_set_variable", {"key": "list.beta", "value": "2"}, env.session_data)

        # list all
        r = execute_tool("project_memory_list_variables", {}, env.session_data)
        cl.check("list all contains alpha", "Lists alpha key", "list.alpha" in r, f"got: {r!r}")
        cl.check("list all contains beta", "Lists beta key", "list.beta" in r, f"got: {r!r}")

        # prefix filter - only list.alpha should match "list.a"
        r2 = execute_tool("project_memory_list_variables", {"prefix": "list.a"}, env.session_data)
        cl.check("prefix filter matches", "Returns key matching prefix", "list.alpha" in r2, f"got: {r2!r}")
        cl.check("prefix filter excludes", "Does not return key not matching prefix", "list.beta" not in r2, f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
