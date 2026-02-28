from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

PATCH = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 hello world
-foo bar
+baz qux
"""

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_apply_patch")
    try:
        env.session_data["memory"]["doc"] = "hello world\nfoo bar\n"

        r = execute_tool("session_memory_apply_patch", {"key": "doc", "patch": PATCH}, env.session_data)
        cl.check("patch applied return", "Applying a valid patch returns a success message", "Patch applied" in r, f"got: {r!r}")

        after = env.session_data["memory"].get("doc", "")
        cl.check("new text present", "Result contains 'baz qux'", "baz qux" in after, f"got: {after!r}")
        cl.check("old text removed", "Result no longer contains 'foo bar'", "foo bar" not in after, f"got: {after!r}")
        cl.check("context line preserved", "Result still contains 'hello world'", "hello world" in after, f"got: {after!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
