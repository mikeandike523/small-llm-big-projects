from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("create_text_file")
    try:
        # create a file in tmp_dir
        target_path = os.path.join(env.tmp_dir, "hello.txt")
        r = execute_tool("create_text_file", {"path": target_path}, env.session_data)
        cl.check("create result", "Result mentions the file was created", "created" in r.lower() or target_path in r, f"got: {r!r}")
        cl.check("file exists", "File actually exists on disk after creation", os.path.isfile(target_path), f"path: {target_path!r}")

        # The tool creates an empty file (touch); verify it is empty or exists
        with open(target_path, "r", encoding="utf-8") as f:
            contents = f.read()
        cl.check("file is empty", "Newly created file is empty (touch semantics)", contents == "", f"contents: {contents!r}")

        # creating the same file again should yield an error
        r2 = execute_tool("create_text_file", {"path": target_path}, env.session_data)
        cl.check("duplicate create error", "Returns error when file already exists", "Error" in r2, f"got: {r2!r}")

        # error when parent directory does not exist (without create_parents)
        bad_path = os.path.join(env.tmp_dir, "nonexistent_parent_xyz", "file.txt")
        r3 = execute_tool("create_text_file", {"path": bad_path}, env.session_data)
        cl.check("missing parent error", "Returns error when parent directory does not exist", "Error" in r3, f"got: {r3!r}")

        # create_parents=True creates missing ancestor directories
        parents_path = os.path.join(env.tmp_dir, "deep", "nested", "dir", "file.txt")
        r4 = execute_tool("create_text_file", {"path": parents_path, "create_parents": True}, env.session_data)
        cl.check("create_parents result", "Result indicates file was created", "Error" not in r4, f"got: {r4!r}")
        cl.check("create_parents file exists", "File actually exists when create_parents=True", os.path.isfile(parents_path), f"path: {parents_path!r}")

        # initial_content writes text into the file on creation
        content_path = os.path.join(env.tmp_dir, "with_content.txt")
        r5 = execute_tool("create_text_file", {"path": content_path, "initial_content": "hello content"}, env.session_data)
        cl.check("initial_content result", "Result indicates file was created", "Error" not in r5, f"got: {r5!r}")
        with open(content_path, "r", encoding="utf-8") as f:
            written = f.read()
        cl.check("initial_content written", "File contains the specified initial content", written == "hello content", f"got: {written!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
