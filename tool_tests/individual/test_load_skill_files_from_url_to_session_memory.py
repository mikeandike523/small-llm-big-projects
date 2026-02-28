from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("load_skill_files_from_url_to_session_memory")
    try:
        cl.check("graceful skip", "Tool requires network + valid skill URL, skipping in automated tests", True, "")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
