from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from src.tools import execute_tool


def _j(r: str) -> dict:
    try:
        return json.loads(r)
    except Exception:
        return {}


def add_checks(cl: CheckList, env: TestEnv) -> None:
    as_: dict = {}
    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "1. numbered item"}, as_)
    cl.check("auto_strip simple", "Leading '1. ' stripped",
             _j(r).get("text") == "numbered item", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "1.2. dot-delimited"}, as_)
    cl.check("auto_strip dot-delimited", "Leading '1.2. ' stripped",
             _j(r).get("text") == "dot-delimited", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "3) paren style"}, as_)
    cl.check("auto_strip paren", "Leading '3) ' stripped",
             _j(r).get("text") == "paren style", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "2) keep prefix", "auto_strip_leading_numbers": False}, as_)
    cl.check("auto_strip disabled", "Prefix preserved when auto_strip=False",
             _j(r).get("text") == "2) keep prefix", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "2.2 no-trailing-marker"}, as_)
    cl.check("auto_strip multi-part no trailing", "Leading '2.2 ' stripped (multi-part, no trailing dot/paren)",
             _j(r).get("text") == "no-trailing-marker", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "1.1.) dot-paren"}, as_)
    cl.check("auto_strip dot-paren", "Leading '1.1.) ' stripped",
             _j(r).get("text") == "dot-paren", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_item", "parent_path": "", "text": "1 bare digit not stripped"}, as_)
    cl.check("auto_strip bare digit not stripped", "Bare '1 ' is NOT stripped (no dot or paren)",
             _j(r).get("text") == "1 bare digit not stripped", f"got: {r!r}")

    r = execute_tool("todo_list", {"action": "add_many_items", "parent_path": "", "texts": ["1. first", "1.2. second"]}, as_)
    stripped = [it["text"] for it in _j(r).get("items", [])]
    cl.check("auto_strip in add_many_items", "Leading numbers stripped from all texts in add_many_items",
             stripped == ["first", "second"], f"got: {stripped!r}")

