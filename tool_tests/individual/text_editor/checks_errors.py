from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["err_key"] = "content"
    fp = os.path.join(env.tmp_dir, "err_file.txt")
    with open(fp, "w") as f:
        f.write("x")

    # Both key and filepath provided
    r = execute_tool("text_editor", {"action": "count_lines", "key": "err_key", "filepath": fp}, env.session_data)
    cl.check("both key and filepath", "Returns error when both key and filepath are given",
             r.startswith("Error:"), f"got: {r!r}")

    # Neither key nor filepath
    r = execute_tool("text_editor", {"action": "count_lines"}, env.session_data)
    cl.check("neither key nor filepath", "Returns error when neither key nor filepath is given",
             r.startswith("Error:"), f"got: {r!r}")

    # Key not in session memory
    r = execute_tool("text_editor", {"action": "count_lines", "key": "err_no_such_key_xyz"}, env.session_data)
    cl.check("unknown key error", "Returns error when key is not in session memory",
             r.startswith("Error:"), f"got: {r!r}")

