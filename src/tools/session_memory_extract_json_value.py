from __future__ import annotations

import json

LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 500

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_extract_json_value",
        "description": (
            "Parse a session memory key as JSON, traverse it using a path, "
            "and return the resulting value. At each step: if the current value is a list, "
            "the step is interpreted as an integer index; if it is a dict, the step is used "
            "as a string key. "
            "Use 'path' (dot-delimited string, e.g. 'foo.bar.0.baz') for normal cases. "
            "Use 'path_steps' (array of strings) only in the rare case that a key in the "
            "JSON object contains a period. Exactly one of 'path' or 'path_steps' must be provided. "
            "Use target='return_value' (default) to get the value inline, or "
            "target='session_memory' with output_session_memory_key to store it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input_session_memory_key": {
                    "type": "string",
                    "description": "The session memory key whose value will be parsed as JSON.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Dot-delimited traversal path, e.g. 'results.0.name'. "
                        "Use this in the normal case. "
                        "Mutually exclusive with path_steps."
                    ),
                },
                "path_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered traversal steps as an array of strings, e.g. ['results', '0', 'name']. "
                        "Use only when a key in the JSON object contains a period. "
                        "Mutually exclusive with path."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "'return_value' (default): return the extracted value inline as a string. "
                        "'session_memory': write the extracted value into a session memory key "
                        "(requires output_session_memory_key). If the extracted value is not a "
                        "string it will be serialized as JSON."
                    ),
                },
                "output_session_memory_key": {
                    "type": "string",
                    "description": (
                        "Required when target='session_memory'. "
                        "The session memory key to store the extracted value into."
                    ),
                },
            },
            "required": ["input_session_memory_key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def _value_to_str(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _traverse(value, steps: list[str]) -> tuple[object, str | None]:
    """Traverse value along steps. Returns (result, error_message)."""
    for i, step in enumerate(steps):
        if isinstance(value, list):
            try:
                idx = int(step)
            except ValueError:
                return None, (
                    f"Error: at step {i} the current value is a list, "
                    f"but step {step!r} is not a valid integer index."
                )
            if idx < -len(value) or idx >= len(value):
                return None, (
                    f"Error: at step {i} index {idx} is out of range "
                    f"(list length {len(value)})."
                )
            value = value[idx]
        elif isinstance(value, dict):
            if step not in value:
                return None, (
                    f"Error: at step {i} key {step!r} not found. "
                    f"Available keys: {list(value.keys())!r}"
                )
            value = value[step]
        else:
            return None, (
                f"Error: at step {i} the current value is {type(value).__name__!r} "
                f"(not a dict or list), cannot traverse further with step {step!r}."
            )
    return value, None


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)

    input_key = args["input_session_memory_key"]
    has_path = "path" in args and args["path"] is not None
    has_steps = "path_steps" in args and args["path_steps"] is not None
    target = args.get("target", "return_value")

    if has_path and has_steps:
        return "Error: provide either 'path' or 'path_steps', not both."
    if not has_path and not has_steps:
        return "Error: one of 'path' or 'path_steps' must be provided."

    if has_path:
        steps = args["path"].split(".")
        path_repr = args["path"]
    else:
        steps = args["path_steps"]
        path_repr = repr(steps)

    raw = memory.get(input_key)
    if raw is None:
        return f"Error: session memory key {input_key!r} not found."
    if not isinstance(raw, str):
        return f"Error: session memory key {input_key!r} does not hold a text value."

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"Error: failed to parse {input_key!r} as JSON: {e}"

    value, err = _traverse(value, steps)
    if err:
        return err

    if target == "session_memory":
        out_key = args.get("output_session_memory_key")
        if not out_key:
            return "Error: target='session_memory' requires output_session_memory_key."
        memory[out_key] = _value_to_str(value)
        return (
            f"Extracted value from {input_key!r} at path {path_repr!r} "
            f"and stored it in session memory key {out_key!r}."
        )

    return _value_to_str(value)
