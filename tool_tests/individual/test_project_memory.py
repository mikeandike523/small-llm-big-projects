from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("project_memory")
    try:
        # --- set ---
        r = execute_tool("project_memory", {"action": "set", "key": "testkey", "value": "testval"}, env.session_data)
        cl.check("set: literal value", "Stores a literal value in project memory", "Stored" in r, f"got: {r!r}")

        env.session_data["memory"]["sesskey"] = "fromSession"
        r2 = execute_tool("project_memory", {"action": "set", "key": "testkey2", "from_session_key": "sesskey"}, env.session_data)
        cl.check("set: from session key", "Copies value from session memory into project memory", "Stored" in r2, f"got: {r2!r}")

        # --- get ---
        execute_tool("project_memory", {"action": "set", "key": "gettest", "value": "myvalue"}, env.session_data)
        r3 = execute_tool("project_memory", {"action": "get", "key": "gettest"}, env.session_data)
        cl.check("get: existing value", "Returns the stored value inline", r3 == "myvalue", f"got: {r3!r}")

        r4 = execute_tool("project_memory", {"action": "get", "key": "nosuchkey"}, env.session_data)
        cl.check("get: missing key", "Returns not-found message for absent key", "not found" in r4, f"got: {r4!r}")

        execute_tool("project_memory", {"action": "set", "key": "loadme", "value": "loaded_content"}, env.session_data)
        r5 = execute_tool("project_memory", {"action": "get", "key": "loadme", "target": "session_memory", "target_session_key": "loaded"}, env.session_data)
        cl.check("get: to session_memory result", "Returns confirmation when writing to session memory", "loaded" in r5.lower(), f"got: {r5!r}")
        session_val = env.session_data["memory"].get("loaded")
        cl.check("get: to session_memory value", "Value written into session memory at specified key", session_val == "loaded_content", f"got: {session_val!r}")

        # --- list ---
        execute_tool("project_memory", {"action": "set", "key": "list.alpha", "value": "1"}, env.session_data)
        execute_tool("project_memory", {"action": "set", "key": "list.beta", "value": "2"}, env.session_data)

        r6 = execute_tool("project_memory", {"action": "list"}, env.session_data)
        cl.check("list: contains alpha", "Lists alpha key", "list.alpha" in r6, f"got: {r6!r}")
        cl.check("list: contains beta", "Lists beta key", "list.beta" in r6, f"got: {r6!r}")

        r7 = execute_tool("project_memory", {"action": "list", "prefix": "list.a"}, env.session_data)
        cl.check("list: prefix filter matches", "Returns key matching prefix", "list.alpha" in r7, f"got: {r7!r}")
        cl.check("list: prefix filter excludes", "Does not return key not matching prefix", "list.beta" not in r7, f"got: {r7!r}")

        # --- delete ---
        execute_tool("project_memory", {"action": "set", "key": "delme", "value": "gone"}, env.session_data)
        r8 = execute_tool("project_memory", {"action": "delete", "key": "delme"}, env.session_data)
        cl.check("delete: existing", "Delete returns success message", "Deleted" in r8, f"got: {r8!r}")

        r9 = execute_tool("project_memory", {"action": "get", "key": "delme"}, env.session_data)
        cl.check("delete: key gone after delete", "Getting deleted key returns not-found message", "not found" in r9, f"got: {r9!r}")

        r10 = execute_tool("project_memory", {"action": "delete", "key": "nosuchkey"}, env.session_data)
        cl.check("delete: non-existent raises", "Deleting missing key returns error string with 'does not exist'", "Failed" in r10 and "does not exist" in r10, f"got: {r10!r}")

        # --- search_by_regex ---
        execute_tool("project_memory", {"action": "set", "key": "searchme", "value": "hello world\nfoo bar\nbaz qux"}, env.session_data)

        r11 = execute_tool("project_memory", {"action": "search_by_regex", "key": "searchme", "pattern": "foo"}, env.session_data)
        cl.check("search_by_regex: pattern matches", "Returns matching lines when pattern is found", "foo" in r11, f"got: {r11!r}")

        r12 = execute_tool("project_memory", {"action": "search_by_regex", "key": "searchme", "pattern": "xyz"}, env.session_data)
        cl.check("search_by_regex: no matches", "Returns no-match message when pattern is not found", "No matches" in r12, f"got: {r12!r}")

        r13 = execute_tool("project_memory", {"action": "search_by_regex", "key": "searchme"}, env.session_data)
        cl.check("search_by_regex: no pattern returns all lines numbered", "Without pattern, returns all lines with line numbers and pipes", "|" in r13 and "hello world" in r13, f"got: {r13!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
