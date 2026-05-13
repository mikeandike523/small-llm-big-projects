from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    # Spaces-indented code
    env.session_data["memory"]["ci_spaces"] = "def foo():\n    pass\n    return 1\n"
    r = execute_tool("text_editor", {"action": "check_indentation", "key": "ci_spaces"}, env.session_data)
    cl.check("spaces detected", "Spaces indentation is reported",
             "space" in r.lower(), f"got: {r!r}")
    cl.check("spaces verdict", "Verdict is 'spaces'",
             "spaces" in r.lower(), f"got: {r!r}")

    # Tabs-indented code
    env.session_data["memory"]["ci_tabs"] = "def foo():\n\tpass\n\treturn 1\n"
    r = execute_tool("text_editor", {"action": "check_indentation", "key": "ci_tabs"}, env.session_data)
    cl.check("tabs detected", "Tabs indentation is reported",
             "tab" in r.lower(), f"got: {r!r}")
    cl.check("tabs verdict", "Verdict is 'tabs'",
             "tabs" in r.lower(), f"got: {r!r}")

    # No indentation
    env.session_data["memory"]["ci_flat"] = "foo\nbar\nbaz\n"
    r = execute_tool("text_editor", {"action": "check_indentation", "key": "ci_flat"}, env.session_data)
    cl.check("no indentation", "Reports no indentation for flat content",
             "no indentation" in r.lower(), f"got: {r!r}")
