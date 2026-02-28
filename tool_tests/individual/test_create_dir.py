from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("create_dir")
    try:
        # create a simple directory
        new_dir = os.path.join(env.tmp_dir, "newdir")
        r = execute_tool("create_dir", {"path": new_dir}, env.session_data)
        cl.check("create simple dir result", "Result mentions success", "created" in r.lower() or new_dir in r, f"got: {r!r}")
        cl.check("simple dir exists", "Directory actually exists on disk", os.path.isdir(new_dir), f"path: {new_dir!r}")

        # create with parents (a/b/c)
        nested_dir = os.path.join(env.tmp_dir, "a", "b", "c")
        r2 = execute_tool("create_dir", {"path": nested_dir, "create_parents": True}, env.session_data)
        cl.check("create nested dir result", "Result mentions success for nested creation", "created" in r2.lower() or nested_dir in r2, f"got: {r2!r}")
        cl.check("nested dir exists", "Nested directory actually exists on disk", os.path.isdir(nested_dir), f"path: {nested_dir!r}")

        # creating the same dir again should give an error (already exists)
        r3 = execute_tool("create_dir", {"path": new_dir}, env.session_data)
        cl.check("duplicate create error", "Returns error when directory already exists", "Error" in r3, f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
