from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    path = os.path.join(env.tmp_dir, "out.txt")
    content = "hello\nworld"

    r = execute_tool(
        "write_text_file", {"path": path, "content": content}, env.session_data
    )
    cl.check(
        "result message",
        "Result mentions the path",
        path in r or "written" in r.lower(),
        f"got: {r!r}",
    )
    cl.check(
        "file exists",
        "File was created on disk",
        os.path.isfile(path),
        f"path: {path!r}",
    )

    with open(path, "r", encoding="utf-8", newline="") as f:
        actual = f.read()
    cl.check(
        "content matches",
        "File content matches the raw content arg",
        actual == content,
        f"got: {actual!r}",
    )

    # create_parents flag
    nested = os.path.join(env.tmp_dir, "sub", "dir", "nested.txt")
    r = execute_tool(
        "write_text_file",
        {"path": nested, "content": "x", "create_parents": True},
        env.session_data,
    )
    cl.check(
        "create_parents",
        "create_parents=True creates missing parent dirs",
        os.path.isfile(nested),
        f"path: {nested!r}",
    )

    # parent dir missing without create_parents
    missing_parent = os.path.join(env.tmp_dir, "no_such_dir", "file.txt")
    r = execute_tool(
        "write_text_file", {"path": missing_parent, "content": "x"}, env.session_data
    )
    cl.check(
        "missing parent error",
        "Returns error when parent dir does not exist",
        r.startswith("Error:"),
        f"got: {r!r}",
    )

    # mutually exclusive args
    r = execute_tool(
        "write_text_file",
        {"path": path, "content": "a", "session_memory_key": "k"},
        env.session_data,
    )
    cl.check(
        "both args error",
        "Returns error when both content and session_memory_key are given",
        r.startswith("Error:"),
        f"got: {r!r}",
    )

    r = execute_tool("write_text_file", {"path": path}, env.session_data)
    cl.check(
        "neither arg error",
        "Returns error when neither content nor session_memory_key is given",
        r.startswith("Error:"),
        f"got: {r!r}",
    )
