from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["buf"] = "hello world"
    r = execute_tool("session_memory_text_editor", {"action": "insert_chars", "key": "buf", "start_char": 5, "text": ","}, env.session_data)
    cl.check("insert_chars: return message", "insert_chars returns success message", "Inserted" in r, f"got: {r!r}")
    cl.check("insert_chars: mid-string insert",
             "Inserting ',' at position 5 yields 'hello, world'",
             env.session_data["memory"]["buf"] == "hello, world",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "world"
    execute_tool("session_memory_text_editor", {"action": "insert_chars", "key": "buf", "start_char": 0, "text": "hello "}, env.session_data)
    cl.check("insert_chars: prepend at 0",
             "Inserting at position 0 prepends the text",
             env.session_data["memory"]["buf"] == "hello world",
             f"got: {env.session_data['memory']['buf']!r}")

    env.session_data["memory"]["buf"] = "hello"
    execute_tool("session_memory_text_editor", {"action": "insert_chars", "key": "buf", "start_char": 999, "text": " world"}, env.session_data)
    cl.check("insert_chars: append beyond end",
             "Inserting at a position beyond end appends the text",
             env.session_data["memory"]["buf"] == "hello world",
             f"got: {env.session_data['memory']['buf']!r}")

    # No EOL conversion -- CRLF in inserted text stays CRLF
    env.session_data["memory"]["buf"] = "line1\nline2\n"
    execute_tool("session_memory_text_editor", {"action": "insert_chars", "key": "buf", "start_char": 6, "text": "extra\r\n"}, env.session_data)
    after = env.session_data["memory"]["buf"]
    cl.check("insert_chars: no EOL conversion",
             "insert_chars writes CRLF verbatim even into an LF buffer",
             "extra\r\n" in after,
             f"got: {after!r}")
