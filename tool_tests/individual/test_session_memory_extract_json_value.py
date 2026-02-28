from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_extract_json_value")
    mem = env.session_data["memory"]

    try:
        # --- Setup: store various JSON structures in session memory ---
        mem["simple_dict"] = json.dumps({"name": "Alice", "age": 30})
        mem["nested"] = json.dumps({"user": {"profile": {"city": "London"}}})
        mem["with_list"] = json.dumps({"items": ["zero", "one", "two"]})
        mem["mixed"] = json.dumps({"results": [{"id": 1, "label": "first"}, {"id": 2, "label": "second"}]})
        mem["string_val"] = json.dumps("hello world")
        mem["number_val"] = json.dumps(42)
        mem["bool_val"] = json.dumps(True)
        mem["dotkey"] = json.dumps({"foo.bar": "dot value"})
        mem["not_json"] = "this is not valid JSON {"

        # --- path: single key from dict ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
        }, env.session_data)
        cl.check("dict single key", "Extracts string value at 'name'", r == "Alice", f"got: {r!r}")

        # --- path: single key, integer value, interpret=True -> indented JSON for non-strings ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "age",
            "enable_interpret_data": True,
        }, env.session_data)
        cl.check("dict int value interpret", "Extracts integer as JSON literal", r == "30", f"got: {r!r}")

        # --- path: nested dict traversal ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "nested",
            "path": "user.profile.city",
        }, env.session_data)
        cl.check("nested dict path", "Traverses nested dicts and returns string as-is", r == "London", f"got: {r!r}")

        # --- path: list index traversal ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "with_list",
            "path": "items.1",
        }, env.session_data)
        cl.check("list index", "Accesses list element at index 1", r == "one", f"got: {r!r}")

        # --- path: list last element via index 2 ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "with_list",
            "path": "items.2",
        }, env.session_data)
        cl.check("list last index", "Accesses list element at index 2", r == "two", f"got: {r!r}")

        # --- path: mixed traversal (dict -> list -> dict) ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "mixed",
            "path": "results.0.label",
        }, env.session_data)
        cl.check("mixed traversal", "Traverses dict->list->dict path", r == "first", f"got: {r!r}")

        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "mixed",
            "path": "results.1.id",
        }, env.session_data)
        cl.check("mixed traversal second item", "Extracts id from second list element", r == "2", f"got: {r!r}")

        # --- enable_interpret_data=True: string returned plain, dict as indented JSON ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
            "enable_interpret_data": True,
        }, env.session_data)
        cl.check("interpret=True string plain", "String returned without quotes when interpret=True", r == "Alice", f"got: {r!r}")

        r_dict = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "nested",
            "path": "user",
            "enable_interpret_data": True,
        }, env.session_data)
        cl.check("interpret=True dict indented", "Dict returned as indented JSON when interpret=True", '"profile"' in r_dict and "\n" in r_dict, f"got: {r_dict!r}")

        # --- enable_interpret_data=False: string is JSON-quoted ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
            "enable_interpret_data": False,
        }, env.session_data)
        cl.check("interpret=False string quoted", "String returned with JSON quotes when interpret=False", r == '"Alice"', f"got: {r!r}")

        # --- path_steps: key containing a period ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "dotkey",
            "path_steps": ["foo.bar"],
        }, env.session_data)
        cl.check("path_steps dotted key", "path_steps allows access to key containing a period", r == "dot value", f"got: {r!r}")

        # --- target=session_memory stores result ---
        execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
            "target": "session_memory",
            "output_session_memory_key": "extracted_name",
        }, env.session_data)
        stored = mem.get("extracted_name")
        cl.check("target session_memory stores value", "Extracted value stored in session memory", stored == "Alice", f"got: {stored!r}")

        # --- target=session_memory with non-string: stores as JSON ---
        execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "age",
            "target": "session_memory",
            "output_session_memory_key": "extracted_age",
        }, env.session_data)
        stored_age = mem.get("extracted_age")
        cl.check("target session_memory non-string as JSON", "Integer stored as JSON string in session memory", stored_age == "30", f"got: {stored_age!r}")

        # --- target=session_memory with interpret=False: string stored quoted ---
        execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
            "target": "session_memory",
            "output_session_memory_key": "extracted_quoted",
            "enable_interpret_data": False,
        }, env.session_data)
        stored_quoted = mem.get("extracted_quoted")
        cl.check("target session_memory interpret=False", "String stored with JSON quotes when interpret=False", stored_quoted == '"Alice"', f"got: {stored_quoted!r}")

        # --- Error: missing session memory key ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "no_such_key",
            "path": "foo",
        }, env.session_data)
        cl.check("error missing key", "Error when input key not found", r.startswith("Error:") and "not found" in r, f"got: {r!r}")

        # --- Error: not valid JSON ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "not_json",
            "path": "foo",
        }, env.session_data)
        cl.check("error invalid JSON", "Error when value is not valid JSON", r.startswith("Error:") and "JSON" in r, f"got: {r!r}")

        # --- Error: dict key not found ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "nonexistent",
        }, env.session_data)
        cl.check("error key not in dict", "Error when path key not in dict", r.startswith("Error:") and "not found" in r, f"got: {r!r}")

        # --- Error: list index out of range ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "with_list",
            "path": "items.99",
        }, env.session_data)
        cl.check("error list index out of range", "Error when list index out of range", r.startswith("Error:") and "out of range" in r, f"got: {r!r}")

        # --- Error: traversing into a non-dict/non-list value ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name.extra",
        }, env.session_data)
        cl.check("error traverse into scalar", "Error when trying to traverse into a string value", r.startswith("Error:"), f"got: {r!r}")

        # --- Error: non-integer step on a list ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "with_list",
            "path": "items.notanint",
        }, env.session_data)
        cl.check("error non-int list step", "Error when non-integer step used on a list", r.startswith("Error:") and "not a valid integer index" in r, f"got: {r!r}")

        # --- Error: both path and path_steps provided ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
            "path_steps": ["name"],
        }, env.session_data)
        cl.check("error both path and path_steps", "Error when both path and path_steps are provided", "Error:" in r, f"got: {r!r}")

        # --- Error: neither path nor path_steps provided ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
        }, env.session_data)
        cl.check("error neither path provided", "Error when neither path nor path_steps provided", "Error:" in r, f"got: {r!r}")

        # --- Error: target=session_memory without output key ---
        r = execute_tool("session_memory_extract_json_value", {
            "input_session_memory_key": "simple_dict",
            "path": "name",
            "target": "session_memory",
        }, env.session_data)
        cl.check("error session_memory no output key", "Error when target=session_memory but no output_session_memory_key", r.startswith("Error:"), f"got: {r!r}")

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
