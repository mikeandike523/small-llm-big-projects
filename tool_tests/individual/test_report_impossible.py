from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("report_impossible")
    try:
        reason_text = "Cannot complete the task because required data is unavailable."
        r = execute_tool("report_impossible", {"reason": reason_text}, env.session_data)

        # result should be a JSON string
        cl.check("result is string", "Returns a string result", isinstance(r, str), f"got type: {type(r).__name__}")

        parsed = None
        try:
            parsed = json.loads(r)
            parse_ok = True
        except Exception:
            parse_ok = False
        cl.check("result is valid JSON", "Result can be parsed as JSON", parse_ok, f"got: {r!r}")

        cl.check("reason field present", "Parsed JSON contains 'reason' field", parsed is not None and "reason" in parsed, f"parsed: {parsed!r}")
        cl.check("reason field value", "The 'reason' field matches the input reason", parsed is not None and parsed.get("reason") == reason_text, f"got reason: {parsed.get('reason') if parsed else None!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
