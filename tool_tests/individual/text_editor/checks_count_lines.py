from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["cl_multi"] = "a\nb\nc\n"
    r = execute_tool("text_editor", {"action": "count_lines", "key": "cl_multi"}, env.session_data)
    cl.check("three lines", "3-line file with trailing newline counts as 3",
             r.strip() == "3", f"got: {r!r}")

    # Trailing newline does not add a phantom line
    env.session_data["memory"]["cl_trail"] = "x\ny\n"
    r = execute_tool("text_editor", {"action": "count_lines", "key": "cl_trail"}, env.session_data)
    cl.check("trailing newline not counted", "Trailing \\n is not counted as an extra line",
             r.strip() == "2", f"got: {r!r}")

    # Single line without trailing newline
    env.session_data["memory"]["cl_single"] = "hello"
    r = execute_tool("text_editor", {"action": "count_lines", "key": "cl_single"}, env.session_data)
    cl.check("single line no newline", "Single line without newline counts as 1",
             r.strip() == "1", f"got: {r!r}")

    # Empty string
    env.session_data["memory"]["cl_empty"] = ""
    r = execute_tool("text_editor", {"action": "count_lines", "key": "cl_empty"}, env.session_data)
    cl.check("empty string", "Empty string has 0 lines",
             r.strip() == "0", f"got: {r!r}")
