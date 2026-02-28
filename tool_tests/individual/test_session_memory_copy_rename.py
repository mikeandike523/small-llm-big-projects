from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_copy_rename")
    try:
        mem = env.session_data["memory"]
        mem["src"] = "original value"

        # copy (keep source)
        r = execute_tool("session_memory_copy_rename", {"source_key": "src", "dest_key": "dst"}, env.session_data)
        cl.check("copy", "Copies source to dest", "Copied" in r or "copied" in r.lower(), f"got: {r!r}")
        cl.check("source preserved after copy", "Source key still exists after copy", "src" in mem, "src was deleted")
        cl.check("dest has value", "Dest key holds the copied value", mem.get("dst") == "original value", f"got: {mem.get('dst')!r}")

        # rename (remove source)
        mem["tosrc"] = "move me"
        r2 = execute_tool("session_memory_copy_rename", {"source_key": "tosrc", "dest_key": "todst", "rename": True}, env.session_data)
        cl.check("rename", "Renames source to dest", "Renamed" in r2 or "renamed" in r2.lower(), f"got: {r2!r}")
        cl.check("source gone after rename", "Source key deleted after rename", "tosrc" not in mem, "tosrc still present")

        # force_overwrite
        mem["a"] = "A"
        mem["b"] = "B"
        r3 = execute_tool("session_memory_copy_rename", {"source_key": "a", "dest_key": "b", "force_overwrite": True}, env.session_data)
        cl.check("force_overwrite", "Force overwrites existing dest key", "Error" not in r3, f"got: {r3!r}")
        cl.check("overwritten value", "Dest holds source value after force overwrite", mem.get("b") == "A", f"got: {mem.get('b')!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
