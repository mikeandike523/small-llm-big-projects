from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    r = execute_tool("session_memory", {"action": "set", "key": "foo", "value": "bar"}, env.session_data)
    cl.check("set: basic", "Stores a new key-value pair in session memory", "Stored" in r, f"got: {r!r}")

    actual = env.session_data["memory"].get("foo")
    cl.check("set: value persisted", "Value is readable back from session memory", actual == "bar", f"got: {actual!r}")

    r2 = execute_tool("session_memory", {"action": "set", "key": "foo", "value": "baz"}, env.session_data)
    cl.check("set: overwrite", "Overwrites an existing key with a new value", "Stored" in r2, f"got: {r2!r}")

    actual2 = env.session_data["memory"].get("foo")
    cl.check("set: overwrite persisted", "Overwritten value is readable", actual2 == "baz", f"got: {actual2!r}")
