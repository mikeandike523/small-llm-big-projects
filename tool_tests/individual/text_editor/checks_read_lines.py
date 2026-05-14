from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool

_KEY = "rl_doc"
_CONTENT = "line one\nline two\nline three\nline four\n"


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"][_KEY] = _CONTENT

    # Full read returns entire content unchanged
    r = execute_tool(
        "text_editor", {"action": "read_lines", "key": _KEY}, env.session_data
    )
    cl.check(
        "full read", "Full read returns entire content", r == _CONTENT, f"got: {r!r}"
    )

    # start_line: returns from line 3 onward
    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "key": _KEY, "start_line": 3},
        env.session_data,
    )
    cl.check(
        "start_line includes tail",
        "start_line=3 returns lines 3 and 4",
        "line three" in r and "line four" in r,
        f"got: {r!r}",
    )
    cl.check(
        "start_line excludes head",
        "start_line=3 excludes lines 1 and 2",
        "line one" not in r and "line two" not in r,
        f"got: {r!r}",
    )

    # end_line: returns up to line 2
    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "key": _KEY, "end_line": 2},
        env.session_data,
    )
    cl.check(
        "end_line includes head",
        "end_line=2 returns lines 1 and 2",
        "line one" in r and "line two" in r,
        f"got: {r!r}",
    )
    cl.check(
        "end_line excludes tail",
        "end_line=2 excludes lines 3 and 4",
        "line three" not in r and "line four" not in r,
        f"got: {r!r}",
    )

    # range: lines 2-3 only
    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "key": _KEY, "start_line": 2, "end_line": 3},
        env.session_data,
    )
    cl.check(
        "range content",
        "Range 2-3 returns exactly lines 2 and 3",
        r == "line two\nline three\n",
        f"got: {r!r}",
    )

    # number_lines: default delimiter ' | '
    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "key": _KEY, "number_lines": True},
        env.session_data,
    )
    cl.check(
        "number_lines default",
        "number_lines prefixes each line with its 1-based number",
        "1 | line one" in r and "4 | line four" in r,
        f"got: {r!r}",
    )

    # number_lines with custom delimiter
    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "key": _KEY, "number_lines": True, "delimiter": ": "},
        env.session_data,
    )
    cl.check(
        "number_lines custom delimiter",
        "Custom delimiter is used between line number and content",
        "1: line one" in r and "2: line two" in r,
        f"got: {r!r}",
    )

    # number_lines respects start_line offset
    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "key": _KEY, "start_line": 3, "number_lines": True},
        env.session_data,
    )
    cl.check(
        "number_lines with start_line",
        "Line numbers reflect the actual file position, not slice offset",
        "3 | line three" in r and "4 | line four" in r,
        f"got: {r!r}",
    )
