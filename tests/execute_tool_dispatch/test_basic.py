"""
Tests for the special_resources dispatch logic in execute_tool.

Uses lightweight stub tool modules — no DB, Redis, or real tools required.
"""
from __future__ import annotations

import sys
import os
import types

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures: list[str] = []


def check(condition: bool, test_name: str, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {test_name}")
    else:
        msg = f"  {FAIL}  {test_name}"
        if detail:
            msg += f"\n       detail: {detail}"
        print(msg)
        _failures.append(test_name)


def get_failures() -> list[str]:
    return _failures


# ---------------------------------------------------------------------------
# Helpers — build minimal stub tool modules
# ---------------------------------------------------------------------------

def _make_tool(name: str, execute_fn) -> types.ModuleType:
    """Return a minimal module that looks like a tool to execute_tool."""
    m = types.ModuleType(f"stub_tool_{name}")
    m.DEFINITION = {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
    }
    m.execute = execute_fn
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_two_arg_tool_receives_no_special_resources():
    """A 2-arg execute() is called without special_resources even when provided."""
    from src.tools import execute_tool, _TOOL_MAP

    received = {}

    def execute(args, session_data):
        received["args"] = args
        received["session_data"] = session_data
        received["called_with_sr"] = False
        return "ok"

    stub = _make_tool("_test_two_arg", execute)
    _TOOL_MAP["_test_two_arg"] = stub
    try:
        result = execute_tool("_test_two_arg", {}, {"x": 1}, special_resources={"foo": "bar"})
        check(result == "ok", "2-arg: tool returns correctly")
        check(received.get("called_with_sr") is False, "2-arg: not called with special_resources")
        check(received.get("session_data") == {"x": 1}, "2-arg: session_data passed correctly")
    finally:
        _TOOL_MAP.pop("_test_two_arg", None)


def test_three_arg_tool_receives_special_resources():
    """A 3-arg execute() receives special_resources when provided."""
    from src.tools import execute_tool, _TOOL_MAP

    received = {}

    def execute(args, session_data, special_resources=None):
        received["special_resources"] = special_resources
        return "ok"

    stub = _make_tool("_test_three_arg", execute)
    _TOOL_MAP["_test_three_arg"] = stub
    try:
        sr = {"emitting_kv_manager": "mock_kv"}
        result = execute_tool("_test_three_arg", {}, {}, special_resources=sr)
        check(result == "ok", "3-arg: tool returns correctly")
        check(received.get("special_resources") is sr, "3-arg: special_resources passed correctly")
    finally:
        _TOOL_MAP.pop("_test_three_arg", None)


def test_three_arg_tool_no_special_resources_provided():
    """A 3-arg tool is called with 2 args when special_resources=None."""
    from src.tools import execute_tool, _TOOL_MAP

    received = {}

    def execute(args, session_data, special_resources=None):
        received["special_resources"] = special_resources
        return "ok"

    stub = _make_tool("_test_three_arg_no_sr", execute)
    _TOOL_MAP["_test_three_arg_no_sr"] = stub
    try:
        result = execute_tool("_test_three_arg_no_sr", {}, {}, special_resources=None)
        check(result == "ok", "3-arg no sr: returns correctly")
        # special_resources is None so we fall back to 2-arg call; the parameter
        # keeps its default value of None
        check(received.get("special_resources") is None, "3-arg no sr: special_resources is None")
    finally:
        _TOOL_MAP.pop("_test_three_arg_no_sr", None)


def test_unknown_tool_returns_error():
    from src.tools import execute_tool
    result = execute_tool("_no_such_tool_xyz", {})
    check("Unknown tool" in result, "unknown tool: returns error string", result)


def test_accepts_special_resources_helper():
    """_accepts_special_resources correctly identifies arity."""
    from src.tools import _accepts_special_resources

    def two(args, session_data): ...
    def three(args, session_data, special_resources=None): ...
    def one(args): ...

    check(_accepts_special_resources(three) is True, "accepts_sr: 3-param fn returns True")
    check(_accepts_special_resources(two) is False, "accepts_sr: 2-param fn returns False")
    check(_accepts_special_resources(one) is False, "accepts_sr: 1-param fn returns False")


def test_project_memory_tools_have_third_param():
    """All 5 project memory tools declare a third parameter."""
    from src.tools import _accepts_special_resources
    from src.tools import (
        project_memory_set_variable,
        project_memory_delete_variable,
        project_memory_get_variable,
        project_memory_list_variables,
        project_memory_search_by_regex,
    )

    tools = [
        ("set_variable", project_memory_set_variable),
        ("delete_variable", project_memory_delete_variable),
        ("get_variable", project_memory_get_variable),
        ("list_variables", project_memory_list_variables),
        ("search_by_regex", project_memory_search_by_regex),
    ]
    for label, module in tools:
        check(
            _accepts_special_resources(module.execute),
            f"project_memory_{label}: has third param",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run() -> list[str]:
    print("=== test_basic.py (execute_tool dispatch) ===")
    test_two_arg_tool_receives_no_special_resources()
    test_three_arg_tool_receives_special_resources()
    test_three_arg_tool_no_special_resources_provided()
    test_unknown_tool_returns_error()
    test_accepts_special_resources_helper()
    test_project_memory_tools_have_third_param()
    return _failures


if __name__ == "__main__":
    failures = run()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
