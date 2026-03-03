from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["buf"] = "hello world"
    r = execute_tool("session_memory_text_editor", {"action": "replace_chars", "key": "buf", "start_char": 6, "end_char": 11, "text": "there"}, env.session_data)
    cl.check("replace_chars: return message", "replace_chars returns success message", "Replaced" in r, f"got: {r!r}")
    cl.check("replace_chars: replacement applied",
             "Replacing chars 6-11 ('world') with 'there' yields 'hello there'",
             env.session_data["memory"]["buf"] == "hello there",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "aXb"
    execute_tool("session_memory_text_editor", {"action": "replace_chars", "key": "buf", "start_char": 1, "end_char": 2, "text": ""}, env.session_data)
    cl.check("replace_chars: delete via empty replacement",
             "Replacing with empty string removes the target chars",
             env.session_data["memory"]["buf"] == "ab",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "ab"
    execute_tool("session_memory_text_editor", {"action": "replace_chars", "key": "buf", "start_char": 1, "end_char": 1, "text": "XY"}, env.session_data)
    cl.check("replace_chars: zero-width range inserts",
             "Replacing an empty range (start==end) inserts text at that position",
             env.session_data["memory"]["buf"] == "aXYb",
             f"got: {env.session_data['memory']['buf']!r}")

    # No EOL conversion
    env.session_data["memory"]["buf"] = "line1\nline2\n"
    execute_tool("session_memory_text_editor", {"action": "replace_chars", "key": "buf", "start_char": 5, "end_char": 6, "text": "\r\n"}, env.session_data)
    after = env.session_data["memory"]["buf"]
    cl.check("replace_chars: no EOL conversion",
             "replace_chars writes CRLF verbatim when requested",
             "\r\n" in after,
             f"got: {after!r}")

    env.session_data["memory"]["buf"] = "abc"
    r_err = execute_tool("session_memory_text_editor", {"action": "replace_chars", "key": "buf", "start_char": 3, "end_char": 2, "text": "x"}, env.session_data)
    cl.check("replace_chars: end < start is error",
             "end_char < start_char returns an error",
             r_err.startswith("Error"),
             f"got: {r_err!r}")
