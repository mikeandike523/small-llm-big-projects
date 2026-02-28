from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_concat")
    try:
        mem = env.session_data["memory"]
        mem["part1"] = "hello "
        mem["part2"] = "world"

        r = execute_tool("session_memory_concat", {"key_a": "part1", "key_b": "part2", "dest_key": "combined"}, env.session_data)
        cl.check("concat two keys", "Concatenates two keys into dest", "Error" not in r, f"got: {r!r}")
        combined = mem.get("combined", "")
        cl.check("combined value", "Destination key holds concatenated value", "hello" in combined and "world" in combined, f"got: {combined!r}")

        # missing key_a (absent treated as empty string)
        r2 = execute_tool("session_memory_concat", {"key_a": "nosuch", "key_b": "part2", "dest_key": "result2"}, env.session_data)
        cl.check("missing key_a treated as empty", "Absent key_a treated as empty string", "Error" not in r2, f"got: {r2!r}")
        result2 = mem.get("result2", "")
        cl.check("result2 equals key_b value", "Result equals key_b value when key_a absent", result2 == "world", f"got: {result2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
