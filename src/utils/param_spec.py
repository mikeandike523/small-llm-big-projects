"""One slbp parameter's definition: type, default, bounds and validation."""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, TypeAdapter, ValidationError

ValueType = Literal["boolean", "float", "integer", "object", "string"]
Scope = Literal["profile", "global"]


class ParamSpec(BaseModel):
    """Full specification for one slbp parameter."""

    name: str
    value_type: ValueType
    description: str
    # Required for every param -- there is no implicit/ambient fallback anywhere else in
    # the system. None is a legitimate, explicit default for "omittable" params (e.g.
    # request_extra_params, override_strict_tool_def, the *.model.name overrides) where
    # unset means "omit this from the request" or "auto-detect" -- that behavior is handled
    # at the call site, NOT here. This field intentionally has no pydantic-level fallback
    # (no `= ...`) so that constructing a ParamSpec without an explicit `default=` raises
    # immediately; validate_registry_defaults() re-checks this with hasattr() as a named,
    # aggregate server-start guard (see its docstring for why hasattr specifically).
    default: Any
    system_only: bool = False  # never forwarded to any LLM request
    scope: Scope = (
        "profile"  # "profile": stored as profiles.<name>.params.* ; "global": stored as params.*
    )
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None  # for value_type "string": allowed values (enum)

    _adapter: Any = PrivateAttr(default=None)

    def model_post_init(self, __context: Any) -> None:
        """Build and cache a pydantic TypeAdapter for numeric types, then sanity-check default."""
        if self.value_type == "integer":
            kw: dict[str, Any] = {}
            if self.min is not None:
                kw["ge"] = int(self.min)
            if self.max is not None:
                kw["le"] = int(self.max)
            ann = Annotated[int, Field(**kw)] if kw else int
            self._adapter = TypeAdapter(ann)
        elif self.value_type == "float":
            kw = {}
            if self.min is not None:
                kw["ge"] = self.min
            if self.max is not None:
                kw["le"] = self.max
            ann = Annotated[float, Field(**kw)] if kw else float
            self._adapter = TypeAdapter(ann)

        # A default of None is always allowed (the "omittable" escape hatch called out
        # above). Any non-None default must itself satisfy this param's own validation,
        # so a typo'd default (wrong type, out of bounds, not in choices) fails loudly at
        # import time instead of surfacing later as a mysterious bad runtime value.
        if self.default is not None:
            self.parse_value(self.default)

    def parse_value(self, raw: Any) -> Any:
        """Parse and validate a raw value. Raises ValueError with a human-readable message."""
        if self.value_type == "boolean":
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str) and raw.lower() in ("true", "false"):
                return raw.lower() == "true"
            raise ValueError(f"'{self.name}' must be 'true' or 'false'")

        if self.value_type == "object":
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"'{self.name}' must be valid JSON: {exc}"
                    ) from exc
            if not isinstance(raw, dict):
                raise ValueError(f"'{self.name}' must be a JSON object")
            return raw

        if self.value_type == "integer":
            try:
                coerced = int(raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"'{self.name}' must be an integer{self._bounds_str()}"
                )
            try:
                return self._adapter.validate_python(coerced)
            except ValidationError:
                raise ValueError(
                    f"'{self.name}' must be an integer{self._bounds_str()}"
                )

        if self.value_type == "float":
            try:
                coerced = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"'{self.name}' must be a number{self._bounds_str()}")
            if math.isnan(coerced) or math.isinf(coerced):
                raise ValueError(f"'{self.name}' must be a finite number")
            try:
                return self._adapter.validate_python(coerced)
            except ValidationError:
                raise ValueError(
                    f"'{self.name}' must be a finite number{self._bounds_str()}"
                )

        # string (optionally constrained to an enum via choices)
        val = str(raw)
        if self.choices is not None and val not in self.choices:
            raise ValueError(f"'{self.name}' must be one of: {', '.join(self.choices)}")
        return val

    def _bounds_str(self) -> str:
        if self.min is not None and self.max is not None:
            lo: Any = int(self.min) if self.value_type == "integer" else self.min
            hi: Any = int(self.max) if self.value_type == "integer" else self.max
            return f" between {lo} and {hi}"
        if self.min is not None:
            v: Any = int(self.min) if self.value_type == "integer" else self.min
            return f" >= {v}"
        if self.max is not None:
            v = int(self.max) if self.value_type == "integer" else self.max
            return f" <= {v}"
        return ""

    def display_type(self) -> str:
        """Human-readable type string for CLI display."""
        if self.choices is not None:
            return f"{self.value_type} ({' | '.join(self.choices)})"
        if self.min is not None and self.max is not None:
            lo: Any = int(self.min) if self.value_type == "integer" else self.min
            hi: Any = int(self.max) if self.value_type == "integer" else self.max
            return f"{self.value_type} ({lo} - {hi})"
        if self.min is not None:
            v: Any = int(self.min) if self.value_type == "integer" else self.min
            return f"{self.value_type} >= {v}"
        if self.max is not None:
            v = int(self.max) if self.value_type == "integer" else self.max
            return f"{self.value_type} <= {v}"
        return self.value_type

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize for the frontend API."""
        d: dict[str, Any] = {
            "name": self.name,
            "value_type": self.value_type,
            "description": self.description,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.choices is not None:
            d["choices"] = list(self.choices)
        return d
