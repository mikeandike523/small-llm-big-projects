from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["buf"] = "hello, world"
    r = execute_tool("session_memory_text_editor", {"action": "delete_chars", "key": "buf", "start_char": 5, "end_char": 7}, env.session_data)
    cl.check("delete_chars: return message", "delete_chars returns success message", "Deleted" in r, f"got: {r!r}")
    cl.check("delete_chars: deletion applied",
             "Deleting chars 5-7 (', ') from 'hello, world' yields 'helloworld'",
             env.session_data["memory"]["buf"] == "helloworld",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "abcde"
    execute_tool("session_memory_text_editor", {"action": "delete_chars", "key": "buf", "start_char": 0, "end_char": 2}, env.session_data)
    cl.check("delete_chars: delete from start",
             "Deleting first two chars yields 'cde'",
             env.session_data["memory"]["buf"] == "cde",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "abcde"
    execute_tool("session_memory_text_editor", {"action": "delete_chars", "key": "buf", "start_char": 3, "end_char": 5}, env.session_data)
    cl.check("delete_chars: delete from end",
             "Deleting last two chars yields 'abc'",
             env.session_data["memory"]["buf"] == "abc",
             f"got: {env.session_data['memory']['buf']!r}")

    # Zero-width delete is a no-op
    env.session_data["memory"]["buf"] = "abc"
    execute_tool("session_memory_text_editor", {"action": "delete_chars", "key": "buf", "start_char": 1, "end_char": 1}, env.session_data)
    cl.check("delete_chars: zero-width is no-op",
             "Deleting an empty range leaves the value unchanged",
             env.session_data["memory"]["buf"] == "abc",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "abc"
    r_err = execute_tool("session_memory_text_editor", {"action": "delete_chars", "key": "buf", "start_char": 3, "end_char": 1}, env.session_data)
    cl.check("delete_chars: end < start is error",
             "end_char < start_char returns an error",
             r_err.startswith("Error"),
             f"got: {r_err!r}")

    # No EOL conversion -- CRLF in the buffer stays as two chars
    env.session_data["memory"]["buf"] = "line1\r\nline2\r\n"
    # Delete only the \r (char 5), leaving \n (char 6) and rest intact
    execute_tool("session_memory_text_editor", {"action": "delete_chars", "key": "buf", "start_char": 5, "end_char": 6}, env.session_data)
    after = env.session_data["memory"]["buf"]
    cl.check("delete_chars: CRLF treated as two chars",
             "Deleting char 5 (the CR of first CRLF) leaves the LF and subsequent chars",
             after == "line1\nline2\r\n",
             f"got: {after!r}")
