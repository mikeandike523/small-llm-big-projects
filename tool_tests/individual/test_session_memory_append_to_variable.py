from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_append_to_variable")
    try:
        # append to new key (absent key is treated as empty string)
        r = execute_tool("session_memory_append_to_variable", {"key": "app", "text": "hello"}, env.session_data)
        cl.check("append to new key", "Appending to non-existent key creates it", "app" in r or "Append" in r or "append" in r.lower(), f"got: {r!r}")
        val = env.session_data["memory"].get("app", "")
        cl.check("new key has value", "New key holds the appended text", "hello" in val, f"got: {val!r}")

        # append to existing
        r2 = execute_tool("session_memory_append_to_variable", {"key": "app", "text": " world"}, env.session_data)
        cl.check("append to existing", "Appending to existing key extends the value", "app" in r2 or "Append" in r2 or "append" in r2.lower(), f"got: {r2!r}")
        val2 = env.session_data["memory"].get("app", "")
        cl.check("combined value", "Combined value contains both parts", "hello" in val2 and "world" in val2, f"got: {val2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
