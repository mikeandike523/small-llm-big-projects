from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    path = os.path.join(env.tmp_dir, "sample.txt")
    content = "hello\nworld"
    with open(path, "wb") as f:
        f.write(content.encode("utf-8"))

    r = execute_tool(
        "read_text_file",
        {"path": path, "session_memory_key": "loaded"},
        env.session_data,
    )
    cl.check(
        "result message",
        "Result mentions the key and session memory",
        "loaded" in r and "session memory" in r.lower(),
        f"got: {r!r}",
    )

    stored = env.session_data["memory"].get("loaded")
    cl.check(
        "content stored",
        "Session memory key holds the exact file content",
        stored == content,
        f"got: {stored!r}",
    )

    # Session memory mode uses newline="" so CRLF is preserved verbatim.
    crlf_path = os.path.join(env.tmp_dir, "crlf.txt")
    crlf_content = "line1\r\nline2\r\n"
    with open(crlf_path, "wb") as f:
        f.write(crlf_content.encode("utf-8"))

    execute_tool(
        "read_text_file",
        {"path": crlf_path, "session_memory_key": "crlf_key"},
        env.session_data,
    )
    stored_crlf = env.session_data["memory"].get("crlf_key")
    cl.check(
        "crlf preserved",
        "Session memory mode preserves CRLF line endings verbatim",
        stored_crlf == crlf_content,
        f"got: {stored_crlf!r}",
    )

    r = execute_tool(
        "read_text_file",
        {"path": path + ".missing", "session_memory_key": "x"},
        env.session_data,
    )
    cl.check(
        "missing file error",
        "Returns an error string for a missing file",
        r.startswith("Error:"),
        f"got: {r!r}",
    )
