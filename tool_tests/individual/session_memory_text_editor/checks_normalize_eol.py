from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["eol_key"] = "line1\r\nline2\r\n"
    r = execute_tool("session_memory_text_editor", {"action": "normalize_eol", "key": "eol_key", "eol": "lf"}, env.session_data)
    cl.check("normalize_eol: to lf return", "Normalizing to LF returns a success message", "LF" in r.upper(), f"got: {r!r}")
    after_lf = env.session_data["memory"].get("eol_key", "")
    cl.check("normalize_eol: no crlf after lf", "Normalized value contains no CRLF sequences", "\r\n" not in after_lf, f"got: {after_lf!r}")
    cl.check("normalize_eol: lf present", "Normalized value contains LF", "\n" in after_lf, f"got: {after_lf!r}")

    env.session_data["memory"]["eol_key"] = "line1\nline2\n"
    r2 = execute_tool("session_memory_text_editor", {"action": "normalize_eol", "key": "eol_key", "eol": "crlf"}, env.session_data)
    cl.check("normalize_eol: to crlf return", "Normalizing to CRLF returns a success message", "CRLF" in r2.upper(), f"got: {r2!r}")
    after_crlf = env.session_data["memory"].get("eol_key", "")
    cl.check("normalize_eol: crlf present", "Normalized value contains CRLF sequences", "\r\n" in after_crlf, f"got: {after_crlf!r}")
