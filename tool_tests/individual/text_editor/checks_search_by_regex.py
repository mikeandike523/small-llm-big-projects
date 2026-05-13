from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool

_KEY = "sr_src"


def add_checks(cl: CheckList, env: TestEnv) -> None:
    env.session_data["memory"][_KEY] = "alpha\nbeta\ngamma\nalpha again\n"

    # Matching lines reported
    r = execute_tool("text_editor", {"action": "search_by_regex", "key": _KEY, "pattern": "alpha"}, env.session_data)
    cl.check("match count", "Reports number of matches in header",
             "2 match" in r, f"got: {r!r}")
    cl.check("match lines present", "Matching lines appear in output",
             "alpha" in r and "alpha again" in r, f"got: {r!r}")
    cl.check("non-matching excluded", "Non-matching line is not in output",
             "beta" not in r and "gamma" not in r, f"got: {r!r}")

    # No matches
    r = execute_tool("text_editor", {"action": "search_by_regex", "key": _KEY, "pattern": "zzznothere"}, env.session_data)
    cl.check("no matches", "Reports no matches when pattern absent",
             "no matches" in r.lower(), f"got: {r!r}")

    # Invalid regex
    r = execute_tool("text_editor", {"action": "search_by_regex", "key": _KEY, "pattern": "["}, env.session_data)
    cl.check("invalid regex error", "Returns error for malformed regex",
             r.startswith("Error:"), f"got: {r!r}")

    # Missing pattern arg
    r = execute_tool("text_editor", {"action": "search_by_regex", "key": _KEY}, env.session_data)
    cl.check("missing pattern error", "Returns error when pattern is missing",
             r.startswith("Error:"), f"got: {r!r}")

    # Empty content
    env.session_data["memory"]["sr_empty"] = ""
    r = execute_tool("text_editor", {"action": "search_by_regex", "key": "sr_empty", "pattern": "."}, env.session_data)
    cl.check("empty content", "Reports empty when content is empty",
             "empty" in r.lower(), f"got: {r!r}")
