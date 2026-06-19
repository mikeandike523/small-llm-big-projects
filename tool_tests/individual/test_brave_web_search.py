from __future__ import annotations
import json as _json

from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool
from src.utils.http.helpers import load_latest_service_tokens_from_db


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("brave_web_search")
    try:
        # Load the brave token from the DB exactly as the tool does.
        try:
            tokens, missing = load_latest_service_tokens_from_db(["brave"])
        except Exception as e:
            cl.skip(f"Could not reach DB to check brave token: {type(e).__name__}: {e}")
            return cl.result()

        if missing:
            cl.skip("brave service token not set in DB — skipping live search test")
            return cl.result()

        # Token is present: run a basic query and verify a successful response.
        r = execute_tool(
            "brave_web_search", {"q": "python programming language"}, env.session_data
        )

        # The endpoint may be unreachable (no network, TLS interception, etc.).
        # On a transport-level failure the tool returns a formatted error
        # carrying "Request failed:" — skip rather than fail, since the live
        # behaviour can't be exercised in this environment.
        if "Request failed:" in r:
            cl.skip("Brave endpoint not reachable — live search test skipped")
            return cl.result()

        cl.check(
            "no error",
            "Tool does not return an error string",
            not r.startswith("Error:"),
            f"got: {r[:200]!r}",
        )

        parsed = None
        try:
            parsed = _json.loads(r)
        except Exception:
            pass

        cl.check(
            "response is json",
            "Result is parseable JSON",
            parsed is not None,
            f"got: {r[:200]!r}",
        )

        cl.check(
            "response is non-empty",
            "Parsed JSON is a non-empty object or array",
            parsed is not None and bool(parsed),
            f"got: {r[:200]!r}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
