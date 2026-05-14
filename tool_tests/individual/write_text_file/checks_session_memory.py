from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"]["file_content"] = "write me to disk"
    path = os.path.join(env.tmp_dir, "from_memory.txt")

    r = execute_tool(
        "write_text_file",
        {"path": path, "session_memory_key": "file_content"},
        env.session_data,
    )
    cl.check(
        "result message",
        "Result mentions the path or char count",
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
        "File content matches what was in session memory",
        actual == "write me to disk",
        f"got: {actual!r}",
    )

    # CRLF written verbatim (tool uses newline="")
    crlf_content = "line1\r\nline2\r\n"
    env.session_data["memory"]["crlf_content"] = crlf_content
    crlf_path = os.path.join(env.tmp_dir, "crlf_out.txt")
    execute_tool(
        "write_text_file",
        {"path": crlf_path, "session_memory_key": "crlf_content"},
        env.session_data,
    )
    with open(crlf_path, "rb") as f:
        raw = f.read()
    cl.check(
        "crlf preserved",
        "CRLF line endings are written verbatim",
        raw == crlf_content.encode("utf-8"),
        f"got: {raw!r}",
    )

    # key not in memory
    r = execute_tool(
        "write_text_file",
        {"path": path, "session_memory_key": "no_such_key"},
        env.session_data,
    )
    cl.check(
        "missing key error",
        "Returns error when session memory key does not exist",
        r.startswith("Error:"),
        f"got: {r!r}",
    )
