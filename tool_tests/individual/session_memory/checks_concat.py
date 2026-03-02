from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    mem = env.session_data["memory"]
    mem["part1"] = "hello "
    mem["part2"] = "world"

    r = execute_tool("session_memory", {"action": "concat", "key_a": "part1", "key_b": "part2", "dest_key": "combined"}, env.session_data)
    cl.check("concat: two keys", "Concatenates two keys into dest", "Error" not in r, f"got: {r!r}")

    combined = mem.get("combined", "")
    cl.check("concat: combined value", "Destination key holds concatenated value",
             "hello" in combined and "world" in combined, f"got: {combined!r}")

    r2 = execute_tool("session_memory", {"action": "concat", "key_a": "nosuch", "key_b": "part2", "dest_key": "result2"}, env.session_data)
    cl.check("concat: missing key_a treated as empty", "Absent key_a treated as empty string", "Error" not in r2, f"got: {r2!r}")

    result2 = mem.get("result2", "")
    cl.check("concat: result equals key_b value", "Result equals key_b value when key_a absent", result2 == "world", f"got: {result2!r}")
