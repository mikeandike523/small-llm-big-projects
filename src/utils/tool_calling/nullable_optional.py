"""Compensate for models that populate every optional tool parameter instead of
omitting it (observed on gpt-5.x: sends 0/""/[]/false rather than leaving the key
out). Gated entirely behind system.hotfix_gpt_aggressive_arg_fill -- callers only
invoke this module when that param is true.

Two directions:
  wrap_tool_defs_nullable()   -- outgoing: union optional properties' type with
                                  "null" so the model has an explicit, distinguishable
                                  way to say "omit this".
  resolve_nulls_to_omitted()  -- incoming: an explicit null for such a property is
                                  translated back to "key absent" before the args
                                  reach the normal validate_tool_args pipeline.

A property whose OWN schema already allows null (rare today; no built-in tool does
this) is a degenerate case: wrapping it would be a no-op, and we can't tell a
model's "I mean omitted" null apart from a genuine null the tool itself assigns
meaning to. Such properties are left unwrapped, a one-time "! caution" warning is
logged, and any null they carry is passed through as a real null rather than
being dropped.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

_warned_nullable_fields: set[tuple[str, str]] = set()


def _schema_allows_null(schema: Any) -> bool:
    """True if this JSON-schema fragment already accepts null on its own terms."""
    if not isinstance(schema, dict):
        return False
    t = schema.get("type")
    if isinstance(t, list) and "null" in t:
        return True
    if t == "null":
        return True
    for combinator in ("anyOf", "oneOf"):
        branches = schema.get(combinator)
        if isinstance(branches, list) and any(
            isinstance(b, dict) and b.get("type") == "null" for b in branches
        ):
            return True
    return False


def _add_null_type(schema: dict) -> dict:
    """Return a copy of schema with its type unioned with null. No-op if type isn't a plain string."""
    t = schema.get("type")
    if not isinstance(t, str):
        return schema
    new_schema = dict(schema)
    new_schema["type"] = [t, "null"]
    return new_schema


def _tool_name_from_def(tool_def: dict) -> str:
    return tool_def.get("function", {}).get("name", "<unknown-tool>")


def wrap_tool_def_nullable(tool_def: dict) -> dict:
    """Return a deep copy of tool_def with optional properties unioned with null.

    Properties already in `required`, or whose schema already allows null, are
    left untouched (the latter logs a one-time "! caution" warning).
    """
    result = copy.deepcopy(tool_def)
    params = result.get("function", {}).get("parameters", {})
    properties = params.get("properties")
    if not isinstance(properties, dict):
        return result

    required = set(params.get("required", []) or [])
    tool_name = _tool_name_from_def(result)

    for field_name, schema in list(properties.items()):
        if field_name in required or not isinstance(schema, dict):
            continue
        if _schema_allows_null(schema):
            key = (tool_name, field_name)
            if key not in _warned_nullable_fields:
                _warned_nullable_fields.add(key)
                logger.warning(
                    "! caution: Tool '%s' field '%s' already had a nullable value in "
                    "its schema -- some OpenAI models cannot differentiate between "
                    "null and omission, so a null the model sends for this field "
                    "will be considered a present null value, not an omission.",
                    tool_name,
                    field_name,
                )
            continue
        properties[field_name] = _add_null_type(schema)

    return result


def wrap_tool_defs_nullable(tool_defs: list[dict]) -> list[dict]:
    """Map wrap_tool_def_nullable over a list of tool definitions."""
    return [wrap_tool_def_nullable(td) for td in tool_defs]


def resolve_nulls_to_omitted(tool_def: dict, args: dict) -> dict:
    """Translate explicit nulls in args back to omitted keys, per wrap_tool_def_nullable's rules.

    Operates against the ORIGINAL (unwrapped) tool_def, since that's the only way to
    tell "we introduced this null option" apart from "this field was always nullable".
    Returns a new dict; does not mutate args.
    """
    params = tool_def.get("function", {}).get("parameters", {})
    properties = params.get("properties")
    if not isinstance(properties, dict):
        return dict(args)

    required = set(params.get("required", []) or [])
    result = dict(args)

    for field_name, value in list(result.items()):
        if value is not None:
            continue
        if field_name in required:
            continue  # let validate_tool_args raise a clear type error
        schema = properties.get(field_name)
        if isinstance(schema, dict) and _schema_allows_null(schema):
            continue  # degenerate case: genuine null, keep it explicit
        del result[field_name]

    return result
