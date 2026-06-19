from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    # Basic replace: swap "beta" for "BETA" using surrounding context lines
    env.session_data["memory"]["ap_basic"] = "alpha\nbeta\ngamma\n"
    r = execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_basic",
            "patch": "@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma",
        },
        env.session_data,
    )
    cl.check(
        "replace result message",
        "apply_patch reports success",
        "applied" in r.lower(),
        f"got: {r!r}",
    )
    stored = env.session_data["memory"].get("ap_basic")
    cl.check(
        "replace content",
        "Replaced line appears in stored value",
        stored == "alpha\nBETA\ngamma\n",
        f"got: {stored!r}",
    )

    # Context-only hunk → error (nothing to change), content unchanged
    env.session_data["memory"]["ap_noop"] = "foo\nbar\n"
    r = execute_tool(
        "text_editor",
        {"action": "apply_patch", "key": "ap_noop", "patch": "@@ -1,2 +1,2 @@\n foo\n bar"},
        env.session_data,
    )
    cl.check(
        "context-only hunk error",
        "Patch with only context lines (no +/-) returns an error and leaves content unchanged",
        r.startswith("Error:") and env.session_data["memory"].get("ap_noop") == "foo\nbar\n",
        f"got: {r!r}",
    )

    # Pure insertion at a position (anchored by @@ header line number)
    env.session_data["memory"]["ap_insert"] = "line1\nline2\nline3\n"
    execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_insert",
            "patch": "@@ -1,3 +2,4 @@\n+inserted",
        },
        env.session_data,
    )
    stored2 = env.session_data["memory"].get("ap_insert")
    cl.check(
        "pure insertion",
        "Position-based pure insertion adds line before target position",
        stored2 == "line1\ninserted\nline2\nline3\n",
        f"got: {stored2!r}",
    )

    # Multiple hunks applied sequentially
    env.session_data["memory"]["ap_multi"] = "a\nb\nc\n"
    execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_multi",
            "patch": "@@ -1,2 +1,2 @@\n a\n-b\n+B\n@@ -2,2 +2,2 @@\n B\n-c\n+C",
        },
        env.session_data,
    )
    cl.check(
        "multiple hunks",
        "Multiple hunks applied in sequence",
        env.session_data["memory"].get("ap_multi") == "a\nB\nC\n",
        f"got: {env.session_data['memory'].get('ap_multi')!r}",
    )

    # Context not found → error
    env.session_data["memory"]["ap_nomatch"] = "alpha\nbeta\ngamma\n"
    r = execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_nomatch",
            "patch": "@@ -1,2 +1,2 @@\n no_such_line\n-beta",
        },
        env.session_data,
    )
    cl.check(
        "no match error",
        "Returns error when context does not match",
        r.startswith("Error:") and "context not found" in r.lower(),
        f"got: {r!r}",
    )

    # Ambiguous context → error
    env.session_data["memory"]["ap_ambig"] = "foo\nbar\nfoo\nbar\n"
    r = execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_ambig",
            "patch": "@@ -1,2 +1,2 @@\n foo\n-bar\n+BAR",
        },
        env.session_data,
    )
    cl.check(
        "ambiguous match error",
        "Returns error when context matches multiple locations",
        r.startswith("Error:") and "matches" in r.lower() and "location" in r.lower(),
        f"got: {r!r}",
    )

    # Missing patch arg
    env.session_data["memory"]["ap_nopatch"] = "x\n"
    r = execute_tool(
        "text_editor", {"action": "apply_patch", "key": "ap_nopatch"}, env.session_data
    )
    cl.check(
        "missing patch error",
        "Returns error when patch arg is missing",
        r.startswith("Error:") and "patch" in r.lower(),
        f"got: {r!r}",
    )

    # Pure insertion without position anchor (no @@ header) → error
    env.session_data["memory"]["ap_nopos"] = "x\n"
    r = execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_nopos",
            "patch": "+orphan_line",
        },
        env.session_data,
    )
    cl.check(
        "no context no position error",
        "Returns error for pure insertion without a position anchor",
        r.startswith("Error:") and "position" in r.lower(),
        f"got: {r!r}",
    )

    # Auto EOL: patch on CRLF content produces CRLF output
    env.session_data["memory"]["ap_crlf"] = "alpha\r\nbeta\r\ngamma\r\n"
    execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "key": "ap_crlf",
            "patch": "@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma",
        },
        env.session_data,
    )
    stored_crlf = env.session_data["memory"].get("ap_crlf")
    cl.check(
        "auto eol crlf",
        "Patch on CRLF content preserves CRLF line endings",
        stored_crlf == "alpha\r\nBETA\r\ngamma\r\n",
        f"got: {stored_crlf!r}",
    )
