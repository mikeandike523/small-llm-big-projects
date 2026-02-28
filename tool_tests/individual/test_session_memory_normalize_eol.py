from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_normalize_eol")
    try:
        # CRLF -> LF
        env.session_data["memory"]["eol_key"] = "line1\r\nline2\r\n"
        r = execute_tool("session_memory_normalize_eol", {"key": "eol_key", "eol": "lf"}, env.session_data)
        cl.check("normalize to lf return", "Normalizing to LF returns a success message", "LF" in r.upper(), f"got: {r!r}")
        after_lf = env.session_data["memory"].get("eol_key", "")
        cl.check("lf result has no crlf", "Normalized value contains no CRLF sequences", "\r\n" not in after_lf, f"got: {after_lf!r}")
        cl.check("lf result has lf", "Normalized value contains LF", "\n" in after_lf, f"got: {after_lf!r}")

        # LF -> CRLF
        env.session_data["memory"]["eol_key"] = "line1\nline2\n"
        r2 = execute_tool("session_memory_normalize_eol", {"key": "eol_key", "eol": "crlf"}, env.session_data)
        cl.check("normalize to crlf return", "Normalizing to CRLF returns a success message", "CRLF" in r2.upper(), f"got: {r2!r}")
        after_crlf = env.session_data["memory"].get("eol_key", "")
        cl.check("crlf result has crlf", "Normalized value contains CRLF sequences", "\r\n" in after_crlf, f"got: {after_crlf!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
