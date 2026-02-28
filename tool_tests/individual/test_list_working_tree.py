from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("list_working_tree")
    original_cwd = os.getcwd()

    # Resolve the project root: the directory that contains src/
    # Walk up from the current file's location until we find a src/ sibling.
    candidate = original_cwd
    while True:
        if os.path.isdir(os.path.join(candidate, "src")):
            project_root = candidate
            break
        parent = os.path.dirname(candidate)
        if parent == candidate:
            project_root = original_cwd
            break
        candidate = parent

    try:
        os.chdir(project_root)

        r = execute_tool("list_working_tree", {}, env.session_data)
        cl.check("non-empty result", "Returns a non-empty listing of the working tree", isinstance(r, str) and len(r.strip()) > 0, f"got: {r!r}")

        # The result should contain at least one file path (e.g. something under src/)
        cl.check("contains src path", "Listing contains at least one entry under src/", "src/" in r, f"got (first 300 chars): {r[:300]!r}")
    except Exception as e:
        cl.record_exception(e)
    finally:
        try:
            os.chdir(original_cwd)
        except Exception:
            pass
    return cl.result()
