from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("list_dir")
    try:
        # Set up: create a file and a subfolder in tmp_dir
        test_file = os.path.join(env.tmp_dir, "list_test_file.txt")
        test_subdir = os.path.join(env.tmp_dir, "list_test_subdir")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("content")
        os.makedirs(test_subdir, exist_ok=True)

        # nested file inside subdir for recursive test
        nested_file = os.path.join(test_subdir, "nested.txt")
        with open(nested_file, "w", encoding="utf-8") as f:
            f.write("nested")

        # basic listing
        r = execute_tool("list_dir", {"path": env.tmp_dir}, env.session_data)
        cl.check("lists file", "Listing includes the created file", "list_test_file.txt" in r, f"got: {r!r}")
        cl.check("lists subdir", "Listing includes the created subfolder", "list_test_subdir" in r, f"got: {r!r}")

        # recursive listing
        r2 = execute_tool("list_dir", {"path": env.tmp_dir, "recursive": True}, env.session_data)
        cl.check("recursive lists nested file", "Recursive listing includes nested file", "nested.txt" in r2, f"got: {r2!r}")

        # filter=files — should include the file, should not include the subdir name with trailing slash
        r3 = execute_tool("list_dir", {"path": env.tmp_dir, "filter": "files", "recursive": True}, env.session_data)
        cl.check("filter files includes file", "Files-only filter includes the top-level file", "list_test_file.txt" in r3, f"got: {r3!r}")
        cl.check("filter files excludes folder", "Files-only filter excludes bare folder name with slash", "list_test_subdir/" not in r3.splitlines(), f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
