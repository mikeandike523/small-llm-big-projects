from __future__ import annotations
import os
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    path = os.path.join(env.tmp_dir, "te_file.txt")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("line1\nline2\nline3\n")

    # Read action via filepath
    r = execute_tool(
        "text_editor", {"action": "count_lines", "filepath": path}, env.session_data
    )
    cl.check(
        "filepath count_lines",
        "count_lines works via filepath",
        r.strip() == "3",
        f"got: {r!r}",
    )

    r = execute_tool(
        "text_editor",
        {"action": "read_lines", "filepath": path, "start_line": 2, "end_line": 2},
        env.session_data,
    )
    cl.check(
        "filepath read_lines range",
        "read_lines range works via filepath",
        "line2" in r and "line1" not in r,
        f"got: {r!r}",
    )

    r = execute_tool(
        "text_editor", {"action": "check_eol", "filepath": path}, env.session_data
    )
    cl.check(
        "filepath check_eol",
        "check_eol works via filepath",
        "lf" in r.lower(),
        f"got: {r!r}",
    )

    # Write action via filepath: apply_patch modifies the file on disk
    r = execute_tool(
        "text_editor",
        {
            "action": "apply_patch",
            "filepath": path,
            "patch": "@@ -1,3 +1,3 @@\n line1\n-line2\n+LINE2\n line3",
        },
        env.session_data,
    )
    cl.check(
        "filepath apply_patch result",
        "apply_patch via filepath reports success",
        "applied" in r.lower(),
        f"got: {r!r}",
    )

    with open(path, "r", encoding="utf-8", newline="") as f:
        on_disk = f.read()
    cl.check(
        "filepath apply_patch on disk",
        "apply_patch writes modified content back to the file",
        "LINE2" in on_disk and "line2" not in on_disk,
        f"got: {on_disk!r}",
    )

    # filepath does not pollute session memory
    cl.check(
        "filepath no memory side effect",
        "filepath mode does not write to session memory",
        "__filepath_buf__" not in env.session_data.get("memory", {}),
        "key leaked into memory",
    )

    # Missing file → error
    r = execute_tool(
        "text_editor",
        {"action": "count_lines", "filepath": path + ".missing"},
        env.session_data,
    )
    cl.check(
        "filepath not found",
        "Returns error for a missing filepath",
        r.startswith("Error:"),
        f"got: {r!r}",
    )
