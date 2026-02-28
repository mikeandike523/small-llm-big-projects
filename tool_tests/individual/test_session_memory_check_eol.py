from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_check_eol")
    try:
        # CRLF content
        env.session_data["memory"]["eol_key"] = "line1\r\nline2\r\n"
        r_crlf = execute_tool("session_memory_check_eol", {"key": "eol_key"}, env.session_data)
        cl.check("CRLF detected", "Result mentions 'CRLF' for CRLF-only content", "CRLF" in r_crlf, f"got: {r_crlf!r}")

        # LF content
        env.session_data["memory"]["eol_key"] = "line1\nline2\n"
        r_lf = execute_tool("session_memory_check_eol", {"key": "eol_key"}, env.session_data)
        cl.check("LF detected", "Result mentions 'LF' for LF-only content", "LF" in r_lf, f"got: {r_lf!r}")

        # mixed content
        env.session_data["memory"]["eol_key"] = "line1\r\nline2\n"
        r_mixed = execute_tool("session_memory_check_eol", {"key": "eol_key"}, env.session_data)
        cl.check("mixed detected", "Result mentions 'mixed' for mixed line endings", "mixed" in r_mixed.lower(), f"got: {r_mixed!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
