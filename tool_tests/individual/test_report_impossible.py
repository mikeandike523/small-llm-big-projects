from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("report_impossible")
    try:
        reason_text = "Cannot complete the task because required data is unavailable."
        r = execute_tool("report_impossible", {"reason": reason_text}, env.session_data)

        cl.check("returns reason string", "Returns the reason text directly as a string",
                 r == reason_text, f"got: {r!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
