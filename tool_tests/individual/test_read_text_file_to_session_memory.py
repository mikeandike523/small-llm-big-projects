from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("read_text_file_to_session_memory")
    try:
        # write a known file to disk
        sample_path = os.path.join(env.tmp_dir, "sample.txt")
        expected_content = "hello from the test file\nline two"
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write(expected_content)

        # load it into session memory
        r = execute_tool(
            "read_text_file_to_session_memory",
            {"filepath": sample_path, "memory_key": "loaded"},
            env.session_data,
        )
        cl.check("result message", "Result message references the file and/or memory key", "loaded" in r or sample_path in r, f"got: {r!r}")

        stored = env.session_data["memory"].get("loaded")
        cl.check("content stored", "Session memory key holds the file content", stored == expected_content, f"got: {stored!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
