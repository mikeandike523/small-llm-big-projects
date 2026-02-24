from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


# -------------------------
# Errors
# -------------------------

class ToolValidationError(Exception):
    """Base class for tool arg validation errors."""


class MissingOrExtraArgumentsError(ToolValidationError):
    """Raised when required args are missing and/or unknown args are present.

    IMPORTANT:
      - Missing is computed relative to `required`.
      - Extra is computed relative to `allowed` (i.e. schema `properties` keys),
        and only when additionalProperties is False.

    This matches JSON Schema / OpenAI tool-parameters semantics:
      * optional args are in properties but not in required
      * additionalProperties:false rejects keys not in properties
    """

    def __init__(
        self,
        tool_name: str,
        provided: Sequence[str],
        required_arguments: Sequence[str],
        allowed_arguments: Sequence[str],
        additional_fields_permitted: bool,
    ):
        self.tool_name = tool_name
        self.provided = list(provided)
        self.required_arguments = list(required_arguments)
        self.allowed_arguments = list(allowed_arguments)
        self.additional_fields_permitted = additional_fields_permitted

        provided_set = set(self.provided)
        required_set = set(self.required_arguments)
        allowed_set = set(self.allowed_arguments)

        # stable ordering
        self.missing = [a for a in self.required_arguments if a not in provided_set]

        # extra keys are ONLY those not declared in properties when additionalProperties is false
        if self.additional_fields_permitted:
            self.extra = []
        else:
            self.extra = [a for a in self.provided if a not in allowed_set]

        super().__init__(str(self))

    def __str__(self) -> str:
        return f"""\
MissingOrExtraArgumentsError

Tool Name: {self.tool_name}
Allowed Arguments: {self.allowed_arguments}
Required Arguments: {self.required_arguments}
Extra Args Permitted: {self.additional_fields_permitted}
Missing: {', '.join(self.missing) if self.missing else '(none)'}
Extra: {', '.join(self.extra) if self.extra else '(none)'}
"""


class InvalidTypeError(ToolValidationError):
    def __init__(self, tool_name: str, path: str, expected: str, got: str):
        self.tool_name = tool_name
        self.path = path
        self.expected = expected
        self.got = got
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.tool_name}: {self.path}: expected {self.expected}, got {self.got}"


class StringConstraintError(ToolValidationError):
    def __init__(self, tool_name: str, path: str, message: str, value: Any):
        self.tool_name = tool_name
        self.path = path
        self.message = message
        self.value = value
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.tool_name}: {self.path}: {self.message} (value={self.value!r})"


class NumberConstraintError(ToolValidationError):
    def __init__(self, tool_name: str, path: str, message: str, value: Any):
        self.tool_name = tool_name
        self.path = path
        self.message = message
        self.value = value
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.tool_name}: {self.path}: {self.message} (value={self.value!r})"


class EnumConstraintError(ToolValidationError):
    def __init__(self, tool_name: str, path: str, allowed: Sequence[Any], value: Any):
        self.tool_name = tool_name
        self.path = path
        self.allowed = list(allowed)
        self.value = value
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"{self.tool_name}: {self.path}: value must be one of {self.allowed!r} "
            f"(value={self.value!r})"
        )


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


class AggregateToolValidationError(ToolValidationError):
    """Collect multiple issues and raise once (optional ergonomic)."""

    def __init__(self, tool_name: str, issues: Sequence[ValidationIssue]):
        self.tool_name = tool_name
        self.issues = list(issues)
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [f"{self.tool_name}: validation failed with {len(self.issues)} issue(s):"]
        lines += [f"  - {i.path}: {i.message}" for i in self.issues]
        return "\n".join(lines)


# -------------------------
# Basic validator (not comprehensive)
# Supports:
# - parameters.type == "object"
# - required
# - additionalProperties (False)
# - properties.<name>.type: string/integer/number/boolean/object
# - string: minLength, maxLength, pattern
# - number: minimum, maximum
# - enum
# -------------------------

_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _tool_name_from_def(tool_def: Mapping[str, Any]) -> str:
    # you showed {"type":"function","function":{...}}
    # but some code uses {"function":{...}} directly
    if "function" in tool_def:
        return tool_def.get("function", {}).get("name", "<unknown-tool>")
    return tool_def.get("name", "<unknown-tool>")


def _params_from_def(tool_def: Mapping[str, Any]) -> Mapping[str, Any]:
    if "function" in tool_def:
        return tool_def.get("function", {}).get("parameters", {}) or {}
    return tool_def.get("parameters", {}) or {}


def validate_tool_args(tool_def: Mapping[str, Any], args: Mapping[str, Any]) -> None:
    """Validate tool args against a subset of JSON Schema constraints.

    NOTE: This is intentionally partial; it focuses on the most common constraints
    used in OpenAI-style tool definitions.

    Raises ToolValidationError on failure.
    """
    tool_name = _tool_name_from_def(tool_def)
    params = _params_from_def(tool_def)

    if params.get("type") != "object":
        raise ToolValidationError(f"{tool_name}: parameters.type must be 'object'")

    if not isinstance(args, Mapping):
        raise InvalidTypeError(tool_name, "$", "object", type(args).__name__)

    properties: dict[str, Any] = params.get("properties", {}) or {}
    allowed: list[str] = list(properties.keys())
    required: list[str] = list(params.get("required", []) or [])

    # JSON Schema semantics:
    #   additionalProperties: false  => no keys outside `properties`.
    #   if missing or omitted => defaults to true.
    additional_fields_permitted: bool = params.get("additionalProperties", True) is not False

    provided_keys = list(args.keys())
    err = MissingOrExtraArgumentsError(
        tool_name=tool_name,
        provided=provided_keys,
        required_arguments=required,
        allowed_arguments=allowed,
        additional_fields_permitted=additional_fields_permitted,
    )
    if err.missing or err.extra:
        raise err

    issues: list[ValidationIssue] = []

    for key, schema in properties.items():
        if key not in args:
            continue  # optional & absent is fine
        _validate_value(
            tool_name=tool_name,
            path=f"$.{key}",
            value=args[key],
            schema=schema,
            issues=issues,
        )

    if issues:
        raise AggregateToolValidationError(tool_name, issues)


def _validate_value(
    tool_name: str,
    path: str,
    value: Any,
    schema: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    expected_type = schema.get("type")
    if expected_type:
        py_t = _JSON_TYPE_MAP.get(expected_type)
        if py_t is None:
            # Unknown type in our partial validator: ignore rather than fail hard.
            return

        # integer should not accept bool (since bool is a subclass of int)
        if expected_type == "integer":
            if not (isinstance(value, int) and not isinstance(value, bool)):
                issues.append(
                    ValidationIssue(path, f"expected integer, got {type(value).__name__}")
                )
                return
        elif expected_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                issues.append(
                    ValidationIssue(path, f"expected number, got {type(value).__name__}")
                )
                return
        else:
            if not isinstance(value, py_t):
                issues.append(
                    ValidationIssue(
                        path, f"expected {expected_type}, got {type(value).__name__}"
                    )
                )
                return

    # enum
    if "enum" in schema:
        allowed = schema["enum"]
        if value not in allowed:
            issues.append(ValidationIssue(path, f"value must be one of {list(allowed)!r}"))
            return

    # string constraints
    if expected_type == "string":
        s: str = value
        min_len = schema.get("minLength")
        if isinstance(min_len, int) and len(s) < min_len:
            issues.append(ValidationIssue(path, f"minLength {min_len} violated"))
        max_len = schema.get("maxLength")
        if isinstance(max_len, int) and len(s) > max_len:
            issues.append(ValidationIssue(path, f"maxLength {max_len} violated"))

        pat = schema.get("pattern")
        if isinstance(pat, str):
            try:
                import re

                if re.search(pat, s) is None:
                    issues.append(ValidationIssue(path, f"pattern {pat!r} did not match"))
            except Exception:
                # If regex is invalid, treat as schema bug; ignore or record.
                issues.append(ValidationIssue(path, "invalid schema regex pattern"))

    # number constraints
    if expected_type in ("integer", "number"):
        # value is already type-checked above
        v = value
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and v < minimum:
            issues.append(ValidationIssue(path, f"minimum {minimum} violated"))
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and v > maximum:
            issues.append(ValidationIssue(path, f"maximum {maximum} violated"))

    # object constraints (very shallow)
    if expected_type == "object":
        sub_props = schema.get("properties")
        if isinstance(sub_props, dict) and isinstance(value, Mapping):
            sub_required = list(schema.get("required", []) or [])
            sub_allowed = list(sub_props.keys())
            sub_additional_permitted = schema.get("additionalProperties", True) is not False

            err = MissingOrExtraArgumentsError(
                tool_name=tool_name,
                provided=list(value.keys()),
                required_arguments=sub_required,
                allowed_arguments=sub_allowed,
                additional_fields_permitted=sub_additional_permitted,
            )
            if err.missing or err.extra:
                issues.append(ValidationIssue(path, str(err)))
                return

            for k, sub_schema in sub_props.items():
                if k in value:
                    _validate_value(
                        tool_name=tool_name,
                        path=f"{path}.{k}",
                        value=value[k],
                        schema=sub_schema,
                        issues=issues,
                    )
