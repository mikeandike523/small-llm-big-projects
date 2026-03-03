from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def _set(env: TestEnv, key: str, value: str) -> None:
    env.session_data["memory"][key] = value


def _get(env: TestEnv, key: str) -> str:
    return env.session_data["memory"].get(key, "")


def add_checks(cl: CheckList, env: TestEnv) -> None:
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
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: replace middle line",
             "banana replaced by blueberry; apple and cherry preserved",
             _get(env, "doc") == "apple\nblueberry\ncherry\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "line one\nline two\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,3 @@
 line one
 line two
+line three
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: add at end",
             "new line appended after existing content",
             _get(env, "doc") == "line one\nline two\nline three\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "keep me\ndelete me\nalso keep\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,3 +1,2 @@
 keep me
-delete me
 also keep
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: delete lines",
             "middle line removed; surrounding lines intact",
             _get(env, "doc") == "keep me\nalso keep\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "second\nthird\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,3 @@
+first
 second
 third
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: add at beginning",
             "new first line prepended before existing lines",
             _get(env, "doc") == "first\nsecond\nthird\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "hello\r\nworld\r\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 hello
-world
+universe
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: crlf preserved",
             "CRLF line endings survive a LF-patch application unchanged",
             _get(env, "doc") == "hello\r\nuniverse\r\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "alpha\nbeta")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: no trailing newline preserved",
             "file without trailing newline has none after patch",
             _get(env, "doc") == "alpha\ngamma",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "alpha\nbeta\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 alpha
-beta
+gamma
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: trailing newline preserved",
             "file with trailing newline retains it after patch",
             _get(env, "doc") == "alpha\ngamma\n",
             f"got: {_get(env, 'doc')!r}")

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
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: multi-hunk",
             "both independent hunks applied correctly in one pass",
             _get(env, "doc") == "A start\nA NEW\nA end\ngap\nB start\nB NEW\nB end\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "one\ntwo\nthree\nfour\nfive\n")
    patch = """\
--- a/file
+++ b/file
@@ -4,2 +4,2 @@
 two
-three
+THREE
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: fuzz offset applies",
             "hunk with line-number off by 2 still applies via fuzzy search",
             _get(env, "doc") == "one\ntwo\nTHREE\nfour\nfive\n",
             f"got: {_get(env, 'doc')!r}")

    _set(env, "doc", "foo\nbar\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 nomatch
-bar
+baz
"""
    r = execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch}, env.session_data)
    cl.check("apply_patch: error on bad context",
             "context lines that exist nowhere in the file return an Error string",
             r.startswith("Error"),
             f"got: {r!r}")

    # disable_auto_eol: CRLF buffer + LF patch -> LF result when disabled
    _set(env, "doc", "hello\r\nworld\r\n")
    patch = """\
--- a/file
+++ b/file
@@ -1,2 +1,2 @@
 hello
-world
+universe
"""
    execute_tool("session_memory_text_editor", {"action": "apply_patch", "key": "doc", "patch": patch, "disable_auto_eol": True}, env.session_data)
    cl.check("apply_patch: disable_auto_eol produces LF on CRLF buffer",
             "With disable_auto_eol=true, patching a CRLF buffer yields LF result",
             _get(env, "doc") == "hello\nuniverse\n",
             f"got: {_get(env, 'doc')!r}")
