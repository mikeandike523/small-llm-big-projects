from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("delete_file")
    try:
        # create a file manually then delete it via tool
        target_path = os.path.join(env.tmp_dir, "to_delete.txt")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("temporary content")

        r = execute_tool("delete_file", {"path": target_path}, env.session_data)
        cl.check("delete result", "Result indicates the file was deleted", "deleted" in r.lower() or target_path in r, f"got: {r!r}")
        cl.check("file gone", "File no longer exists on disk after deletion", not os.path.exists(target_path), f"path: {target_path!r}")

        # delete non-existent file — should return an error-like message
        r2 = execute_tool("delete_file", {"path": target_path}, env.session_data)
        cl.check("non-existent error", "Returns error message for a non-existent file", "Error" in r2 or "not exist" in r2.lower(), f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
