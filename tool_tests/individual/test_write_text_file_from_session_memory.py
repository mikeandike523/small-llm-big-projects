from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("write_text_file_from_session_memory")
    try:
        # seed session memory with content to write
        expected_content = "write me to disk"
        env.session_data["memory"]["outfile_content"] = expected_content

        output_path = os.path.join(env.tmp_dir, "output.txt")
        r = execute_tool(
            "write_text_file_from_session_memory",
            {"memory_key": "outfile_content", "filepath": output_path},
            env.session_data,
        )
        cl.check("result message", "Result message references the key and/or file path", "outfile_content" in r or output_path in r, f"got: {r!r}")
        cl.check("file exists", "Output file was created on disk", os.path.isfile(output_path), f"path: {output_path!r}")

        with open(output_path, "r", encoding="utf-8") as f:
            actual = f.read()
        cl.check("content matches", "File content matches what was in session memory", actual == expected_content, f"got: {actual!r}")

        # error case: key not in memory
        r2 = execute_tool(
            "write_text_file_from_session_memory",
            {"memory_key": "nosuchkey_xyz", "filepath": os.path.join(env.tmp_dir, "nope.txt")},
            env.session_data,
        )
        cl.check("missing key error", "Returns error when memory key does not exist", "Error" in r2 or "not found" in r2.lower(), f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
