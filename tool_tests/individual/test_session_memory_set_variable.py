from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_set_variable")
    try:
        # basic set
        r = execute_tool("session_memory_set_variable", {"key": "foo", "value": "bar"}, env.session_data)
        cl.check("basic set", "Stores a new key-value pair in session memory", "Stored" in r, f"got: {r!r}")

        # value is actually in memory
        actual = env.session_data["memory"].get("foo")
        cl.check("value persisted", "Value is readable back from session memory", actual == "bar", f"got: {actual!r}")

        # overwrite
        r2 = execute_tool("session_memory_set_variable", {"key": "foo", "value": "baz"}, env.session_data)
        cl.check("overwrite", "Overwrites an existing key with a new value", "Stored" in r2, f"got: {r2!r}")
        actual2 = env.session_data["memory"].get("foo")
        cl.check("overwrite persisted", "Overwritten value is readable", actual2 == "baz", f"got: {actual2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
