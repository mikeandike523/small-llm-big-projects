from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    mem = env.session_data["memory"]
    mem["tosrc"] = "move me"

    r = execute_tool("session_memory", {"action": "rename", "source_key": "tosrc", "dest_key": "todst"}, env.session_data)
    cl.check("rename: basic", "Renames source to dest", "Renamed" in r or "renamed" in r.lower(), f"got: {r!r}")
    cl.check("rename: source gone", "Source key deleted after rename", "tosrc" not in mem, "tosrc still present")
    cl.check("rename: dest has value", "Dest key holds the moved value", mem.get("todst") == "move me", f"got: {mem.get('todst')!r}")

    mem["c"] = "C"
    mem["d"] = "D"
    r2 = execute_tool("session_memory", {"action": "rename", "source_key": "c", "dest_key": "d", "force_overwrite": True}, env.session_data)
    cl.check("rename: force_overwrite", "Force overwrites existing dest key during rename", "Error" not in r2, f"got: {r2!r}")
    cl.check("rename: source gone after force overwrite", "Source deleted even with force_overwrite", "c" not in mem, "c still present")
    cl.check("rename: dest updated", "Dest holds renamed value", mem.get("d") == "C", f"got: {mem.get('d')!r}")
