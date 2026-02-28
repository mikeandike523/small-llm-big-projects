from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("remove_dir")
    try:
        # remove an empty directory
        empty_dir = os.path.join(env.tmp_dir, "empty_to_remove")
        os.makedirs(empty_dir, exist_ok=True)
        r = execute_tool("remove_dir", {"path": empty_dir}, env.session_data)
        cl.check("remove empty dir result", "Result indicates directory was removed", "removed" in r.lower() or empty_dir in r, f"got: {r!r}")
        cl.check("empty dir gone", "Empty directory no longer exists after removal", not os.path.exists(empty_dir), f"path: {empty_dir!r}")

        # remove a non-empty directory with recursive=True
        non_empty_dir = os.path.join(env.tmp_dir, "non_empty_to_remove")
        os.makedirs(non_empty_dir, exist_ok=True)
        with open(os.path.join(non_empty_dir, "inside.txt"), "w", encoding="utf-8") as f:
            f.write("content")
        r2 = execute_tool("remove_dir", {"path": non_empty_dir, "recursive": True}, env.session_data)
        cl.check("remove non-empty dir result", "Result indicates directory was removed recursively", "removed" in r2.lower() or non_empty_dir in r2, f"got: {r2!r}")
        cl.check("non-empty dir gone", "Non-empty directory no longer exists after recursive removal", not os.path.exists(non_empty_dir), f"path: {non_empty_dir!r}")

        # remove non-existent directory — should return error
        r3 = execute_tool("remove_dir", {"path": os.path.join(env.tmp_dir, "does_not_exist_xyz")}, env.session_data)
        cl.check("non-existent dir error", "Returns error for non-existent directory", "Error" in r3 or "not exist" in r3.lower(), f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
