from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    path = os.path.join(env.tmp_dir, "sample.txt")
    content = "hello\nworld"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    r = execute_tool("read_text_file", {"path": path}, env.session_data)
    cl.check(
        "returns content",
        "Direct read returns the file contents",
        r == content,
        f"got: {r!r}",
    )

    r = execute_tool("read_text_file", {"path": path + ".missing"}, env.session_data)
    cl.check(
        "file not found",
        "Returns an error string for a missing file",
        r.startswith("Error:"),
        f"got: {r!r}",
    )

    r = execute_tool("read_text_file", {"path": env.tmp_dir}, env.session_data)
    cl.check(
        "directory error",
        "Returns an error string when path is a directory",
        r.startswith("Error:"),
        f"got: {r!r}",
    )
