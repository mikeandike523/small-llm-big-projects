from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def _set(env: TestEnv, key: str, value: str) -> None:
    env.session_data["memory"][key] = value


def _get(env: TestEnv, key: str) -> str:
    return env.session_data["memory"].get(key, "")


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_apply_patch")
    try:

        # ------------------------------------------------------------------
        # replace middle line
        #   before : apple / banana / cherry  (trailing \n)
        #   patch  : replace banana -> blueberry
        #   after  : apple / blueberry / cherry  (trailing \n)
        # ------------------------------------------------------------------
        _set(env, "doc", "apple\nbanana\ncherry\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,3 +1,3 @@
 apple
-banana
+blueberry
 cherry
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("replace middle line",
                 "banana replaced by blueberry; apple and cherry preserved",
                 _get(env, "doc") == "apple\nblueberry\ncherry\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # add at end
        #   before : line one / line two  (trailing \n)
        #   patch  : append line three
        #   after  : line one / line two / line three  (trailing \n)
        # ------------------------------------------------------------------
        _set(env, "doc", "line one\nline two\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,3 @@
 line one
 line two
+line three
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("add at end",
                 "new line appended after existing content",
                 _get(env, "doc") == "line one\nline two\nline three\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # delete lines 1
        #   before : keep me / delete me / also keep  (trailing \n)
        #   patch  : remove middle line
        #   after  : keep me / also keep  (trailing \n)
        # ------------------------------------------------------------------
        _set(env, "doc", "keep me\ndelete me\nalso keep\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,3 +1,2 @@
 keep me
-delete me
 also keep
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("delete lines 1",
                 "middle line removed; surrounding lines intact",
                 _get(env, "doc") == "keep me\nalso keep\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # add at beginning
        #   before : second / third  (trailing \n)
        #   patch  : prepend first
        #   after  : first / second / third  (trailing \n)
        # ------------------------------------------------------------------
        _set(env, "doc", "second\nthird\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,3 @@
+first
 second
 third
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("add at beginning",
                 "new first line prepended before existing lines",
                 _get(env, "doc") == "first\nsecond\nthird\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # crlf preserved
        #   before : hello\r\n / world\r\n  (CRLF)
        #   patch  : replace world -> universe  (LF-only patch text)
        #   after  : hello\r\n / universe\r\n  (CRLF preserved)
        # ------------------------------------------------------------------
        _set(env, "doc", "hello\r\nworld\r\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 hello
-world
+universe
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("crlf preserved",
                 "CRLF line endings survive a LF-patch application unchanged",
                 _get(env, "doc") == "hello\r\nuniverse\r\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # no trailing newline preserved
        #   before : alpha / beta  (no trailing \n)
        #   patch  : replace beta -> gamma
        #   after  : alpha / gamma  (still no trailing \n)
        # ------------------------------------------------------------------
        _set(env, "doc", "alpha\nbeta")      # deliberately no trailing newline
        patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("no trailing newline preserved",
                 "file without trailing newline has none after patch",
                 _get(env, "doc") == "alpha\ngamma",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # trailing newline preserved
        #   before : alpha / beta\n  (with trailing \n)
        #   patch  : replace beta -> gamma  (same patch as above)
        #   after  : alpha / gamma\n  (trailing \n kept)
        # ------------------------------------------------------------------
        _set(env, "doc", "alpha\nbeta\n")    # with trailing newline
        patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("trailing newline preserved",
                 "file with trailing newline retains it after patch",
                 _get(env, "doc") == "alpha\ngamma\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # multi-hunk patch
        #   before : A start / A middle / A end / gap / B start / B middle / B end
        #   patch  : hunk 1 replaces A middle; hunk 2 replaces B middle
        #   after  : A start / A NEW / A end / gap / B start / B NEW / B end
        # ------------------------------------------------------------------
        _set(env, "doc", "A start\nA middle\nA end\ngap\nB start\nB middle\nB end\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,3 +1,3 @@
 A start
-A middle
+A NEW
 A end
@@ -5,3 +5,3 @@
 B start
-B middle
+B NEW
 B end
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("multi-hunk patch",
                 "both independent hunks applied correctly in one pass",
                 _get(env, "doc") == "A start\nA NEW\nA end\ngap\nB start\nB NEW\nB end\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # fuzz offset applies
        #   before : one / two / three / four / five
        #   patch  : header says @@ -4,2 but matching content (two/three) is at line 2
        #            => offset = -2, within ±3 fuzz tolerance
        #   after  : one / two / THREE / four / five
        # ------------------------------------------------------------------
        _set(env, "doc", "one\ntwo\nthree\nfour\nfive\n")
        patch = """\
--- a/file
+++ b/file
@@ -4,2 +4,2 @@
 two
-three
+THREE
"""
        execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("fuzz offset applies",
                 "hunk with line-number off by 2 still applies via fuzzy search",
                 _get(env, "doc") == "one\ntwo\nTHREE\nfour\nfive\n",
                 f"got: {_get(env, 'doc')!r}")

        # ------------------------------------------------------------------
        # error on bad context
        #   before : foo / bar
        #   patch  : context line 'nomatch' does not exist anywhere in file
        #   result : tool returns an Error string, file unchanged
        # ------------------------------------------------------------------
        _set(env, "doc", "foo\nbar\n")
        patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 nomatch
-bar
+baz
"""
        r = execute_tool("session_memory_apply_patch", {"key": "doc", "patch": patch}, env.session_data)
        cl.check("error on bad context",
                 "context lines that exist nowhere in the file return an Error string",
                 r.startswith("Error"),
                 f"got: {r!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
