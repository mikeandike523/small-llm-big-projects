from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["key"] = "a\nb\nc\n"
    r = execute_tool("session_memory_text_editor", {"action": "replace_lines", "key": "key", "start_line": 2, "end_line": 2, "text": "B"}, env.session_data)
    cl.check("replace_lines: single line return", "Replacing line 2 returns a success message", "Replaced" in r, f"got: {r!r}")

    after_single = env.session_data["memory"].get("key", "")
    cl.check("replace_lines: line 2 replaced", "Second line is now 'B'", "B" in after_single, f"got: {after_single!r}")
    cl.check("replace_lines: old line 2 gone", "Original 'b' is no longer present", "\nb\n" not in after_single, f"got: {after_single!r}")

    env.session_data["memory"]["key"] = "a\nb\nc\n"
    r2 = execute_tool("session_memory_text_editor", {"action": "replace_lines", "key": "key", "start_line": 1, "end_line": 2, "text": "X\nY"}, env.session_data)
    cl.check("replace_lines: range return", "Replacing lines 1-2 returns a success message", "Replaced" in r2, f"got: {r2!r}")

    after_range = env.session_data["memory"].get("key", "")
    lines = after_range.splitlines()
    cl.check("replace_lines: first line is X", "First line is now 'X'", len(lines) >= 1 and lines[0] == "X", f"got lines: {lines!r}")
    cl.check("replace_lines: second line is Y", "Second line is now 'Y'", len(lines) >= 2 and lines[1] == "Y", f"got lines: {lines!r}")
    cl.check("replace_lines: third line is c", "Third line is still 'c'", len(lines) >= 3 and lines[2] == "c", f"got lines: {lines!r}")

    # auto-EOL: replacing in a CRLF buffer should produce CRLF-only result
    env.session_data["memory"]["key"] = "a\r\nb\r\nc\r\n"
    execute_tool("session_memory_text_editor", {"action": "replace_lines", "key": "key", "start_line": 2, "end_line": 2, "text": "B"}, env.session_data)
    after_crlf = env.session_data["memory"].get("key", "")
    cl.check("replace_lines: auto-EOL CRLF preserved",
             "Replacing a line in a CRLF buffer yields CRLF-only result",
             "\r\n" in after_crlf and "\n" not in after_crlf.replace("\r\n", ""),
             f"got: {after_crlf!r}")
    cl.check("replace_lines: auto-EOL content correct",
             "Replaced line content is present",
             "B" in after_crlf, f"got: {after_crlf!r}")

    # disable_auto_eol: LF replacement text stays LF even in CRLF buffer
    env.session_data["memory"]["key"] = "a\r\nb\r\nc\r\n"
    execute_tool("session_memory_text_editor", {"action": "replace_lines", "key": "key", "start_line": 2, "end_line": 2, "text": "B", "disable_auto_eol": True}, env.session_data)
    after_raw = env.session_data["memory"].get("key", "")
    cl.check("replace_lines: disable_auto_eol writes verbatim",
             "With disable_auto_eol, replacement LF line is not converted to CRLF",
             "B\n" in after_raw and "B\r\n" not in after_raw, f"got: {after_raw!r}")
