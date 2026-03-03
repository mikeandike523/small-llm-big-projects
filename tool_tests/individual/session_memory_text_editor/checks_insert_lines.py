from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["text"] = "line1\nline2\nline3\n"
    r = execute_tool("session_memory_text_editor", {"action": "insert_lines", "key": "text", "before_line": 1, "text": "line0"}, env.session_data)
    cl.check("insert_lines: prepend return", "Inserting before line 1 returns a success message", "Inserted" in r, f"got: {r!r}")

    after_prepend = env.session_data["memory"].get("text", "")
    cl.check("insert_lines: prepend starts with line0", "line0 is now the first line", after_prepend.startswith("line0"), f"got: {after_prepend!r}")
    cl.check("insert_lines: prepend preserves line1", "Original line1 is still present", "line1" in after_prepend, f"got: {after_prepend!r}")

    env.session_data["memory"]["text"] = "line1\nline2\nline3\n"
    r2 = execute_tool("session_memory_text_editor", {"action": "insert_lines", "key": "text", "before_line": 99, "text": "appended"}, env.session_data)
    cl.check("insert_lines: append return", "Inserting before a line beyond end returns a success message", "Inserted" in r2, f"got: {r2!r}")

    after_append = env.session_data["memory"].get("text", "")
    cl.check("insert_lines: append result ends with appended", "New text appears at the end",
             after_append.rstrip("\n").endswith("appended"), f"got: {after_append!r}")

    # auto-EOL: inserting LF text into CRLF buffer should produce all-CRLF output
    env.session_data["memory"]["text"] = "line1\r\nline2\r\nline3\r\n"
    execute_tool("session_memory_text_editor", {"action": "insert_lines", "key": "text", "before_line": 2, "text": "inserted"}, env.session_data)
    after_crlf = env.session_data["memory"].get("text", "")
    cl.check("insert_lines: auto-EOL CRLF preserved",
             "Inserting LF text into CRLF buffer yields CRLF-only result",
             "\r\n" in after_crlf and "\n" not in after_crlf.replace("\r\n", ""),
             f"got: {after_crlf!r}")
    cl.check("insert_lines: auto-EOL inserted line present",
             "The inserted line text is present in the CRLF result",
             "inserted" in after_crlf, f"got: {after_crlf!r}")

    # disable_auto_eol: result should be written verbatim (mixed endings OK)
    env.session_data["memory"]["text"] = "line1\r\nline2\r\n"
    execute_tool("session_memory_text_editor", {"action": "insert_lines", "key": "text", "before_line": 2, "text": "lf_line\n", "disable_auto_eol": True}, env.session_data)
    after_raw = env.session_data["memory"].get("text", "")
    cl.check("insert_lines: disable_auto_eol writes verbatim",
             "With disable_auto_eol, LF-terminated inserted line is not converted",
             "lf_line\n" in after_raw, f"got: {after_raw!r}")
