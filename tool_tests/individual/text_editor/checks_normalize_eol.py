from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    # CRLF → LF
    env.session_data["memory"]["neol_crlf"] = "line1\r\nline2\r\nline3\r\n"
    r = execute_tool(
        "text_editor",
        {"action": "normalize_eol", "key": "neol_crlf", "eol": "lf"},
        env.session_data,
    )
    cl.check(
        "normalize result message",
        "Result mentions normalization",
        "normalized" in r.lower(),
        f"got: {r!r}",
    )
    stored = env.session_data["memory"].get("neol_crlf")
    cl.check(
        "crlf removed",
        "CRLF sequences are gone after normalization to LF",
        "\r\n" not in stored,
        f"got: {stored!r}",
    )
    cl.check(
        "lf remains",
        "LF endings are present after normalization",
        "\n" in stored,
        f"got: {stored!r}",
    )

    # LF → CRLF
    env.session_data["memory"]["neol_lf"] = "a\nb\nc\n"
    execute_tool(
        "text_editor",
        {"action": "normalize_eol", "key": "neol_lf", "eol": "crlf"},
        env.session_data,
    )
    stored2 = env.session_data["memory"].get("neol_lf")
    cl.check(
        "to crlf",
        "LF endings converted to CRLF",
        "\r\n" in stored2,
        f"got: {stored2!r}",
    )
    cl.check(
        "no bare lf after crlf",
        "No bare LF remains after CRLF normalization",
        stored2 == "a\r\nb\r\nc\r\n",
        f"got: {stored2!r}",
    )

    # Missing eol arg
    env.session_data["memory"]["neol_x"] = "x\n"
    r = execute_tool(
        "text_editor", {"action": "normalize_eol", "key": "neol_x"}, env.session_data
    )
    cl.check(
        "missing eol error",
        "Returns error when eol arg is missing",
        r.startswith("Error:"),
        f"got: {r!r}",
    )
