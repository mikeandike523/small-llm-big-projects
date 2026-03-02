from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["eol_key"] = "line1\r\nline2\r\n"
    r_crlf = execute_tool("session_memory_text_editor", {"action": "check_eol", "key": "eol_key"}, env.session_data)
    cl.check("check_eol: CRLF detected", "Result mentions 'CRLF' for CRLF-only content", "CRLF" in r_crlf, f"got: {r_crlf!r}")

    env.session_data["memory"]["eol_key"] = "line1\nline2\n"
    r_lf = execute_tool("session_memory_text_editor", {"action": "check_eol", "key": "eol_key"}, env.session_data)
    cl.check("check_eol: LF detected", "Result mentions 'LF' for LF-only content", "LF" in r_lf, f"got: {r_lf!r}")

    env.session_data["memory"]["eol_key"] = "line1\r\nline2\n"
    r_mixed = execute_tool("session_memory_text_editor", {"action": "check_eol", "key": "eol_key"}, env.session_data)
    cl.check("check_eol: mixed detected", "Result mentions 'mixed' for mixed line endings", "mixed" in r_mixed.lower(), f"got: {r_mixed!r}")
