"""
Standalone tool runner. Executes a single tool call and prints the result.

Usage:
    python run_tool.py <tool_name> [--<key> <value> | --<key>=<value> | --<bool_key>] ...

Each CLI value is first read as a string, then coerced according to the
tool's parameter schema:
  string params   -> raw string
  integer params  -> decimal integer
  number params   -> integer or float
  boolean params  -> bare flag or true/false-style value
  array params    -> repeat the same flag once per item
  object params   -> JSON object, or repeated key=value entries for string maps

Example:
    python run_tool.py list_dir --path src --max_depth 2
    python run_tool.py host_shell --command git --command_args status --command_args=--short

Environment is loaded from .env at the repo root (credentials, service tokens, etc.)
Session memory uses Redis if available, falls back to a plain dict.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Load .env before importing anything that touches DB / Redis / credentials
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(_repo_root / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment


# ---------------------------------------------------------------------------
# Session data
# ---------------------------------------------------------------------------

def _make_session_data() -> dict:
    """Build a minimal session_data dict that mirrors the real agentic loop."""
    cwd = str(_repo_root)

    # Try Redis-backed memory (same as tool_tests) so stateful tools work fully.
    try:
        import uuid

        import redis

        from src.utils.redis_dict import RedisDict

        r = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        r.ping()  # fail fast if Redis is not running
        hash_key = f"run_tool:session:{uuid.uuid4().hex[:8]}"
        memory = RedisDict(r, hash_key)
        _cleanup_redis = lambda: r.delete(hash_key)  # noqa: E731
    except Exception:
        memory = {}
        _cleanup_redis = lambda: None  # noqa: E731

    return {
        "memory": memory,
        "initial_cwd": cwd,
        "_cleanup": _cleanup_redis,
    }


def _get_tool_definition(tool_name: str) -> dict[str, Any] | None:
    from src.tools import _TOOL_MAP

    module = _TOOL_MAP.get(tool_name)
    if module is None:
        return None
    return getattr(module, "DEFINITION", None)


def _get_parameters_schema(tool_name: str) -> dict[str, Any]:
    tool_def = _get_tool_definition(tool_name)
    if tool_def is None:
        raise KeyError(tool_name)
    return tool_def.get("function", {}).get("parameters", {}) or {}


def _parse_bool(raw: str, *, key: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(
        f"invalid boolean for --{key}: {raw!r} "
        "(expected true/false/yes/no/on/off/1/0)"
    )


def _parse_integer(raw: str, *, key: str) -> int:
    try:
        return int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"invalid integer for --{key}: {raw!r}") from exc


def _parse_number(raw: str, *, key: str) -> int | float:
    try:
        if any(ch in raw.lower() for ch in ".e"):
            return float(raw)
        return int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"invalid number for --{key}: {raw!r}") from exc


def _parse_json_value(raw: str, *, key: str, expected: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {expected} for --{key}: {exc}") from exc


def _coerce_scalar_value(raw: str, schema: Mapping[str, Any], *, key: str) -> Any:
    if "anyOf" in schema:
        stripped = raw.strip()
        for option in schema.get("anyOf", []):
            option_type = option.get("type")
            if option_type == "object" and stripped.startswith("{") and stripped.endswith("}"):
                return _parse_json_value(raw, key=key, expected="object")
            if option_type == "array" and stripped.startswith("[") and stripped.endswith("]"):
                return _parse_json_value(raw, key=key, expected="array")
        for option in schema.get("anyOf", []):
            try:
                return _coerce_scalar_value(raw, option, key=key)
            except ValueError:
                continue
        raise ValueError(f"could not parse --{key} according to any supported schema option")

    expected_type = schema.get("type")
    if expected_type == "string" or expected_type is None:
        return raw
    if expected_type == "integer":
        return _parse_integer(raw, key=key)
    if expected_type == "number":
        return _parse_number(raw, key=key)
    if expected_type == "boolean":
        return _parse_bool(raw, key=key)
    if expected_type == "object":
        return _parse_json_value(raw, key=key, expected="object")
    if expected_type == "array":
        value = _parse_json_value(raw, key=key, expected="array")
        if not isinstance(value, list):
            raise ValueError(f"invalid array for --{key}: expected JSON array")
        return value
    if expected_type == "null":
        if raw.strip().lower() != "null":
            raise ValueError(f"invalid null for --{key}: {raw!r}")
        return None
    return raw


def _coerce_object_values(raw_values: list[str], schema: Mapping[str, Any], *, key: str) -> dict[str, Any]:
    properties = schema.get("properties")
    additional = schema.get("additionalProperties")

    if isinstance(properties, dict):
        if len(raw_values) != 1:
            raise ValueError(
                f"--{key} expects a single JSON object value when object properties are defined"
            )
        value = _parse_json_value(raw_values[0], key=key, expected="object")
        if not isinstance(value, dict):
            raise ValueError(f"invalid object for --{key}: expected JSON object")
        return value

    if isinstance(additional, dict) and additional.get("type") == "string":
        parsed: dict[str, str] = {}
        for raw in raw_values:
            if "=" not in raw:
                raise ValueError(
                    f"invalid object entry for --{key}: {raw!r} "
                    "(expected item in key=value form)"
                )
            sub_key, sub_value = raw.split("=", 1)
            if not sub_key:
                raise ValueError(f"invalid object entry for --{key}: empty key")
            parsed[sub_key] = sub_value
        return parsed

    if len(raw_values) != 1:
        raise ValueError(f"--{key} expects a single JSON object value")
    value = _parse_json_value(raw_values[0], key=key, expected="object")
    if not isinstance(value, dict):
        raise ValueError(f"invalid object for --{key}: expected JSON object")
    return value


def _coerce_values_for_schema(
    raw_values: list[str | None],
    schema: Mapping[str, Any],
    *,
    key: str,
) -> Any:
    expected_type = schema.get("type")

    if expected_type == "array":
        item_schema = schema.get("items", {}) or {}
        values: list[Any] = []
        for raw in raw_values:
            if raw is None:
                raise ValueError(f"--{key} requires a value for each array item")
            stripped = raw.strip()
            if len(raw_values) == 1 and stripped.startswith("[") and stripped.endswith("]"):
                parsed = _parse_json_value(raw, key=key, expected="array")
                if not isinstance(parsed, list):
                    raise ValueError(f"invalid array for --{key}: expected JSON array")
                return parsed
            values.append(_coerce_scalar_value(raw, item_schema, key=key))
        return values

    if expected_type == "object":
        present_values = [raw for raw in raw_values if raw is not None]
        if len(present_values) != len(raw_values):
            raise ValueError(f"--{key} requires a value")
        return _coerce_object_values(present_values, schema, key=key)

    if len(raw_values) > 1:
        raise ValueError(f"--{key} may not be provided more than once")

    raw = raw_values[0]
    if expected_type == "boolean":
        if raw is None:
            return True
        return _parse_bool(raw, key=key)

    if raw is None:
        raise ValueError(f"--{key} requires a value")

    return _coerce_scalar_value(raw, schema, key=key)


def parse_tool_cli_args(tool_name: str, tokens: list[str]) -> dict[str, Any]:
    params = _get_parameters_schema(tool_name)
    properties: dict[str, Any] = params.get("properties", {}) or {}
    required: list[str] = list(params.get("required", []) or [])
    additional_allowed = params.get("additionalProperties", True) is not False

    raw_args: dict[str, list[str | None]] = defaultdict(list)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("--"):
            raise ValueError(f"unexpected argument {tok!r}")
        if tok == "--":
            raise ValueError("bare '--' is not supported")

        if "=" in tok:
            key, _, raw = tok[2:].partition("=")
            raw_args[key].append(raw)
        else:
            key = tok[2:]
            next_token = tokens[i + 1] if i + 1 < len(tokens) else None
            if next_token is not None and not next_token.startswith("--"):
                raw_args[key].append(next_token)
                i += 1
            else:
                raw_args[key].append(None)
        i += 1

    provided = list(raw_args.keys())
    missing = [key for key in required if key not in raw_args]
    extra = [] if additional_allowed else [key for key in provided if key not in properties]
    if missing or extra:
        parts: list[str] = []
        if missing:
            parts.append(f"missing required args: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected args: {', '.join(extra)}")
        raise ValueError("; ".join(parts))

    parsed_args: dict[str, Any] = {}
    for key, values in raw_args.items():
        schema = properties.get(key)
        if schema is None:
            if additional_allowed:
                if len(values) != 1 or values[0] is None:
                    raise ValueError(
                        f"--{key} requires exactly one value because it is not defined in the schema"
                    )
                parsed_args[key] = values[0]
                continue
            raise ValueError(f"unexpected arg --{key}")
        parsed_args[key] = _coerce_values_for_schema(values, schema, key=key)

    return parsed_args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    from src.tools import execute_tool
    from src.utils.tool_calling.arguments import ToolValidationError, validate_tool_args

    parser = argparse.ArgumentParser(
        prog="run_tool.py",
        description="Execute a single tool call and print the result.",
        add_help=True,
    )
    parser.add_argument("tool_name", help="Name of the tool to run")

    parsed, unknown = parser.parse_known_args()
    tool_name = parsed.tool_name

    tool_def = _get_tool_definition(tool_name)
    if tool_def is None:
        parser.error(f"unknown tool {tool_name!r}")

    try:
        args = parse_tool_cli_args(tool_name, unknown)
        validate_tool_args(tool_def, args)
    except (ValueError, ToolValidationError) as exc:
        parser.error(str(exc))

    # on_chunk: print progress chunks in blue as they arrive, mirroring how the
    # UI renders streamingResult before the final tool_result replaces it.
    _BLUE = b"\033[34m"
    _RESET = b"\033[0m"
    _had_chunks = [False]

    def _on_chunk(text: str) -> None:
        _had_chunks[0] = True
        sys.stdout.buffer.write(_BLUE + text.encode("utf-8", errors="replace") + _RESET)
        sys.stdout.buffer.flush()

    special_resources = {"on_chunk": _on_chunk}

    session_data = _make_session_data()
    cleanup = session_data.pop("_cleanup")

    try:
        result = execute_tool(tool_name, args, session_data, special_resources)
        if _had_chunks[0]:
            sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.write((result + "\n").encode("utf-8", errors="replace"))
    finally:
        cleanup()


if __name__ == "__main__":
    main()
