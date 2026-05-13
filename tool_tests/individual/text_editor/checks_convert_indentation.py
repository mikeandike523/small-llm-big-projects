from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    # Spaces → tabs (default 4 spaces per tab)
    env.session_data["memory"]["cvt_spaced"] = "def foo():\n    pass\n    return 1\n"
    r = execute_tool("text_editor", {"action": "convert_indentation", "key": "cvt_spaced", "to": "tabs"}, env.session_data)
    cl.check("spaces to tabs result", "Result message mentions indentation conversion",
             "convert" in r.lower() or "indentation" in r.lower(), f"got: {r!r}")
    stored = env.session_data["memory"].get("cvt_spaced")
    cl.check("tabs present", "Converted content uses tab characters",
             "\t" in stored, f"got: {stored!r}")
    cl.check("leading spaces removed", "4-space indentation is replaced (no leading spaces)",
             "    pass" not in stored and "    return" not in stored, f"got: {stored!r}")

    # Tabs → spaces (default 4 spaces per tab)
    env.session_data["memory"]["cvt_tabbed"] = "def foo():\n\tpass\n\treturn 1\n"
    execute_tool("text_editor", {"action": "convert_indentation", "key": "cvt_tabbed", "to": "spaces"}, env.session_data)
    stored2 = env.session_data["memory"].get("cvt_tabbed")
    cl.check("spaces present", "Converted content uses space indentation",
             "    pass" in stored2, f"got: {stored2!r}")
    cl.check("tabs removed", "Tab characters are removed",
             "\tpass" not in stored2, f"got: {stored2!r}")

    # Custom spaces_per_tab=2
    env.session_data["memory"]["cvt_tab2"] = "root:\n\tchild\n"
    execute_tool("text_editor", {"action": "convert_indentation", "key": "cvt_tab2", "to": "spaces", "spaces_per_tab": 2}, env.session_data)
    stored3 = env.session_data["memory"].get("cvt_tab2")
    cl.check("custom spaces_per_tab", "spaces_per_tab=2 produces 2-space indentation",
             stored3 == "root:\n  child\n", f"got: {stored3!r}")

    # Missing 'to' arg
    env.session_data["memory"]["cvt_err"] = "  foo\n"
    r = execute_tool("text_editor", {"action": "convert_indentation", "key": "cvt_err"}, env.session_data)
    cl.check("missing to error", "Returns error when 'to' arg is missing",
             r.startswith("Error:"), f"got: {r!r}")
