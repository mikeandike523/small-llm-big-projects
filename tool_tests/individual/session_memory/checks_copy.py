from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def add_checks(cl: CheckList, env: TestEnv) -> None:
    mem = env.session_data["memory"]
    mem["src"] = "original value"

    r = execute_tool("session_memory", {"action": "copy", "source_key": "src", "dest_key": "dst"}, env.session_data)
    cl.check("copy: basic", "Copies source to dest", "Copied" in r or "copied" in r.lower(), f"got: {r!r}")
    cl.check("copy: source preserved", "Source key still exists after copy", "src" in mem, "src was deleted")
    cl.check("copy: dest has value", "Dest key holds the copied value", mem.get("dst") == "original value", f"got: {mem.get('dst')!r}")

    mem["a"] = "A"
    mem["b"] = "B"
    r2 = execute_tool("session_memory", {"action": "copy", "source_key": "a", "dest_key": "b", "force_overwrite": True}, env.session_data)
    cl.check("copy: force_overwrite", "Force overwrites existing dest key", "Error" not in r2, f"got: {r2!r}")
    cl.check("copy: overwritten value", "Dest holds source value after force overwrite", mem.get("b") == "A", f"got: {mem.get('b')!r}")

    # no force_overwrite -> error
    mem["x"] = "X"
    mem["y"] = "Y"
    r3 = execute_tool("session_memory", {"action": "copy", "source_key": "x", "dest_key": "y"}, env.session_data)
    cl.check("copy: blocked without force_overwrite", "Returns error when dest exists and force_overwrite not set",
             "Error" in r3, f"got: {r3!r}")
