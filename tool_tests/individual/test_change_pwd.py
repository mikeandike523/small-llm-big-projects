from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("change_pwd")
    original_cwd = os.getcwd()
    try:
        # change to tmp_dir
        r = execute_tool("change_pwd", {"path": env.tmp_dir}, env.session_data)
        cl.check("change to tmp_dir", "Result mentions the target path", env.tmp_dir.replace("\\", "/") in r or os.path.basename(env.tmp_dir) in r, f"got: {r!r}")

        # change back to original
        r2 = execute_tool("change_pwd", {"path": original_cwd}, env.session_data)
        cl.check("change back", "Can change back to original cwd without error", "Error" not in r2, f"got: {r2!r}")

        # attempt change to non-existent dir
        r3 = execute_tool("change_pwd", {"path": "/nonexistent_tooltest_xyz"}, env.session_data)
        cl.check("non-existent dir error", "Returns error for non-existent directory", "Error" in r3, f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    finally:
        try:
            os.chdir(original_cwd)
        except Exception:
            pass
    return cl.result()
