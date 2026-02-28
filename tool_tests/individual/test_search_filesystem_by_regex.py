from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("search_filesystem_by_regex")
    try:
        # write a file with known content
        search_file = os.path.join(env.tmp_dir, "search_me.txt")
        with open(search_file, "w", encoding="utf-8") as f:
            f.write("apple banana cherry")

        # matching pattern
        r = execute_tool(
            "search_filesystem_by_regex",
            {"pattern": "banana", "path": env.tmp_dir},
            env.session_data,
        )
        cl.check("match found", "Result contains the matched word", "banana" in r, f"got: {r!r}")

        # non-matching pattern
        r2 = execute_tool(
            "search_filesystem_by_regex",
            {"pattern": "mango_xyz_not_here", "path": env.tmp_dir},
            env.session_data,
        )
        cl.check("no matches message", "Result indicates no matches for unmatched pattern", "No matches" in r2 or "no matches" in r2.lower(), f"got: {r2!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
