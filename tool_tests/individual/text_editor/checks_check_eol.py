from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    # LF-only content
    env.session_data["memory"]["eol_lf"] = "line1\nline2\nline3\n"
    r = execute_tool("text_editor", {"action": "check_eol", "key": "eol_lf"}, env.session_data)
    cl.check("lf reported", "LF-only content reports LF endings",
             "lf" in r.lower(), f"got: {r!r}")
    cl.check("lf uniform", "LF-only content reports uniform style",
             "uniform" in r.lower(), f"got: {r!r}")
    cl.check("lf no crlf mention", "LF-only content does not mention CRLF count",
             "crlf" not in r.lower(), f"got: {r!r}")

    # CRLF content
    env.session_data["memory"]["eol_crlf"] = "line1\r\nline2\r\nline3\r\n"
    r = execute_tool("text_editor", {"action": "check_eol", "key": "eol_crlf"}, env.session_data)
    cl.check("crlf reported", "CRLF content reports CRLF endings",
             "crlf" in r.lower(), f"got: {r!r}")
    cl.check("crlf uniform", "CRLF content reports uniform style",
             "uniform" in r.lower(), f"got: {r!r}")

    # Mixed content
    env.session_data["memory"]["eol_mixed"] = "line1\nline2\r\nline3\n"
    r = execute_tool("text_editor", {"action": "check_eol", "key": "eol_mixed"}, env.session_data)
    cl.check("mixed reported", "Mixed content reports mixed style",
             "mixed" in r.lower(), f"got: {r!r}")

    # Empty string
    env.session_data["memory"]["eol_empty"] = ""
    r = execute_tool("text_editor", {"action": "check_eol", "key": "eol_empty"}, env.session_data)
    cl.check("empty no endings", "Empty string reports no line endings",
             "no line endings" in r.lower(), f"got: {r!r}")
