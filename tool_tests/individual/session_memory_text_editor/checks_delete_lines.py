from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["key"] = "a\nb\nc\nd\n"
    r = execute_tool("session_memory_text_editor", {"action": "delete_lines", "key": "key", "start_line": 1, "end_line": 1}, env.session_data)
    cl.check("delete_lines: first line return", "Deleting line 1 returns a success message", "Deleted" in r, f"got: {r!r}")

    after_first = env.session_data["memory"].get("key", "")
    cl.check("delete_lines: first line removed", "Value no longer starts with 'a'", not after_first.startswith("a"), f"got: {after_first!r}")
    cl.check("delete_lines: second line is now first", "Value now starts with 'b'", after_first.startswith("b"), f"got: {after_first!r}")

    r2 = execute_tool("session_memory_text_editor", {"action": "delete_lines", "key": "key", "start_line": 2, "end_line": 3}, env.session_data)
    cl.check("delete_lines: range return", "Deleting lines 2-3 returns a success message", "Deleted" in r2, f"got: {r2!r}")

    after_range = env.session_data["memory"].get("key", "")
    cl.check("delete_lines: range removed", "Only 'b' line remains", after_range.strip() == "b", f"got: {after_range!r}")

    # auto-EOL: deleting from a CRLF buffer keeps CRLF endings
    env.session_data["memory"]["key"] = "a\r\nb\r\nc\r\nd\r\n"
    execute_tool("session_memory_text_editor", {"action": "delete_lines", "key": "key", "start_line": 2, "end_line": 2}, env.session_data)
    after_crlf = env.session_data["memory"].get("key", "")
    cl.check("delete_lines: auto-EOL CRLF preserved",
             "Deleting from a CRLF buffer keeps CRLF line endings",
             "\r\n" in after_crlf and "\n" not in after_crlf.replace("\r\n", ""),
             f"got: {after_crlf!r}")
    cl.check("delete_lines: auto-EOL deleted line gone",
             "The deleted line is absent",
             "b" not in after_crlf.splitlines(), f"got: {after_crlf!r}")
