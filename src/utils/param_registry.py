"""
Single source of truth for all slbp parameter definitions.
Includes names, value types, descriptions, min/max constraints, and Pydantic-based validation.
"""
from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, TypeAdapter, ValidationError

ValueType = Literal["boolean", "float", "integer", "object", "string"]

_SAMPLER_NAMESPACES: tuple[str, ...] = (
    "watchdog.model",
    "summarizer.model",
    "patchrewriter.model",
)


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
    scope: Scope = "profile"  # "profile": stored as profiles.<name>.params.* ; "global": stored as params.*
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
                    raise ValueError(f"'{self.name}' must be valid JSON: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"'{self.name}' must be a JSON object")
            return raw

        if self.value_type == "integer":
            try:
                coerced = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"'{self.name}' must be an integer{self._bounds_str()}")
            try:
                return self._adapter.validate_python(coerced)
            except ValidationError:
                raise ValueError(f"'{self.name}' must be an integer{self._bounds_str()}")

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
                raise ValueError(f"'{self.name}' must be a finite number{self._bounds_str()}")

        # string (optionally constrained to an enum via choices)
        val = str(raw)
        if self.choices is not None and val not in self.choices:
            raise ValueError(
                f"'{self.name}' must be one of: {', '.join(self.choices)}"
            )
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


# ---------------------------------------------------------------------------
# Shared sampler suffix specs (temperature / top_p / top_k / max_tokens / extras)
# ---------------------------------------------------------------------------

_SAMPLER_SUFFIX_KWARGS: dict[str, dict[str, Any]] = {
    "temperature": {
        "value_type": "float",
        "min": 0.0,
        "max": 2.0,
        "default": None,  # unset: omit from the request, provider applies its own default
        "description": (
            "Controls randomness. 0.0 is fully deterministic; 2.0 is very random. "
            "Typical values: 0.2 - 0.8."
        ),
    },
    "top_p": {
        "value_type": "float",
        "min": 0.0,
        "max": 1.0,
        "default": None,  # unset: omit from the request, provider applies its own default
        "description": (
            "Nucleus sampling. Only the smallest set of tokens whose cumulative probability "
            "<= top_p are considered. 1.0 disables nucleus sampling."
        ),
    },
    "top_k": {
        "value_type": "integer",
        "min": 1,
        "default": None,  # unset: omit from the request, provider applies its own default
        "description": "Limits the token candidate pool to the K most probable tokens at each step.",
    },
    "max_tokens": {
        "value_type": "integer",
        "min": 1,
        "default": None,  # unset: omit from the request, provider applies its own default
        "description": "Maximum number of tokens to generate in a single response.",
    },
    "request_extra_params": {
        "value_type": "object",
        "default": None,  # unset: omit entirely -- never send `null` for this key
        "description": (
            "Extra parameters merged into every API request for this call type. "
            'Must be a valid JSON object, e.g. {"reasoning":{"effort":"low"}}. '
            "Applies ONLY to this namespace -- never merged with other namespaces."
        ),
    },
}

# ---------------------------------------------------------------------------
# Registry: single dict from param name -> ParamSpec
# ---------------------------------------------------------------------------

REGISTRY: dict[str, ParamSpec] = {}

# Sampler params across all four namespaces
for _ns in ("model", *_SAMPLER_NAMESPACES):
    for _suffix, _kwargs in _SAMPLER_SUFFIX_KWARGS.items():
        _name = f"{_ns}.{_suffix}"
        REGISTRY[_name] = ParamSpec(name=_name, **_kwargs)

# Per-sampler model-override params: optionally use a different model for each
# watchdog/sampler. Set name to the model identifier for the same endpoint.
# Unset (default): the profile's main model is used for all samplers.
_SAMPLER_MODEL_OVERRIDES: dict[str, str] = {
    "watchdog.model.name": (
        "Override the model used by all watchdog samplers (skill selector, "
        "final-answer selector, task title, continuation, and hang-triage). "
        "Unset: use the profile's main model."
    ),
    "summarizer.model.name": (
        "Override the model used by the summarizer (subturn compaction and "
        "summarize_memory_item). Unset: use the profile's main model."
    ),
    "patchrewriter.model.name": (
        "Override the model used by the patch rewriter watchdog (repair of "
        "failing apply_patch calls). Unset: use the profile's main model."
    ),
}
for _name, _desc in _SAMPLER_MODEL_OVERRIDES.items():
    REGISTRY[_name] = ParamSpec(
        name=_name, value_type="string", system_only=True, default=None, description=_desc
    )

# model.* extras (system-only flags, not forwarded to the LLM API)
REGISTRY["model.irat"] = ParamSpec(
    name="model.irat",
    value_type="boolean",
    system_only=True,
    default=False,
    description=(
        "Enable interim-response-as-thinking for new sessions. "
        "When true, interim assistant content between tool calls is shown in the thinking "
        "panel instead of a char-count bubble. Useful for non-thinking models that narrate "
        "reasoning as text."
    ),
)

REGISTRY["model.known_max_context"] = ParamSpec(
    name="model.known_max_context",
    value_type="integer",
    min=0,
    system_only=True,
    default=None,  # unset: context-usage display feature is disabled
    description=(
        "Known maximum context length for this model, if available. "
        "When set and per-exchange usage data is available (e.g., from OpenRouter), "
        "the frontend can display a visual indicator showing how close one is to hitting "
        "the context limit. Optional; if not set or the model does not report usage, "
        "this feature is disabled."
    ),
)

# system.* params
REGISTRY["system.return_value_max_chars"] = ParamSpec(
    name="system.return_value_max_chars",
    value_type="integer",
    min=1,
    default=None,  # unset: stubbing/truncation is disabled entirely (no cap applied)
    description=(
        "Maximum inline tool return characters before stubbing. "
        "When a tool result exceeds this, it is truncated to a preview and the full "
        "content stored under a session memory key (stubs.*) for chunk retrieval."
    ),
)
REGISTRY["system.blank_response_retries"] = ParamSpec(
    name="system.blank_response_retries",
    value_type="integer",
    min=0,
    default=0,
    description=(
        "Silent LLM retries before injecting a todo-nudge when the model emits a blank "
        "response with no tool calls. 0 = nudge immediately (default). "
        "Skipped when model.temperature is 0 (deterministic). Typical useful range: 1-2."
    ),
)
REGISTRY["system.strict_dirty"] = ParamSpec(
    name="system.strict_dirty",
    value_type="boolean",
    default=False,
    description=(
        "Controls how strictly the dirty-file cache blocks tool calls. "
        "false (default): only block if the file has never been read -- useful for models "
        "that prefer calling apply_patch multiple times over writing multi-hunk patches. "
        "true: also block if the file has been modified since it was last read."
    ),
)
REGISTRY["system.enable_patch_rewriter"] = ParamSpec(
    name="system.enable_patch_rewriter",
    value_type="boolean",
    default=False,
    description=(
        "Enable the patch-rewriter watchdog for failing apply_patch calls. "
        "false (default): a patch that does not apply cleanly is passed through to "
        "the tool and the failure is surfaced to the agent -- smarter models often "
        "use the 'patch failed' feedback (and surrounding conversation context) to "
        "self-correct whitespace/context errors on the next turn. "
        "true: an out-of-band patchrewriter.model sampler silently attempts to repair "
        "the patch before it runs, so the agent never sees the failure. Useful for "
        "less capable models that do not recover well from patch errors on their own."
    ),
)
REGISTRY["system.override_strict_tool_def"] = ParamSpec(
    name="system.override_strict_tool_def",
    value_type="boolean",
    default=None,  # unset: automatic per-dialect decision applies (see description)
    description=(
        "Override the automatic per-dialect decision (see "
        "src/utils/llm/dialect.py:should_force_tool_strict) about whether to inject "
        "`strict` onto every outgoing tool definition. Unset (the default -- not merely "
        "'false', but never having been set at all; use `slbp param unset` to restore "
        "this): the automatic decision applies -- currently, force strict:false for real "
        "OpenAI (Chat Completions or Responses) and for OpenRouter models with 'openai' "
        "or 'gpt' in the name, since the Responses API silently auto-attempts strict mode "
        "when the field is omitted, promoting optional properties into `required` "
        "server-side. Set true or false: skip the automatic decision and inject that "
        "literal value on every tool everywhere, regardless of dialect/model."
    ),
)
REGISTRY["system.create_file_auto_eol"] = ParamSpec(
    name="system.create_file_auto_eol",
    value_type="string",
    choices=["enabled", "enabled_silent", "disabled"],
    default="enabled_silent",
    description=(
        "Auto-normalize line endings of newly created files (create_text_file, or "
        "write_text_file to a path that did not previously exist). The target EOL is "
        "detected from the session's INITIAL cwd: a .gitattributes 'eol=lf'/'eol=crlf' "
        "directive wins first, then a *.code-workspace 'files.eol' setting (JSONC), else "
        "the host platform default (CRLF on Windows, LF on mac/Linux). "
        "enabled_silent (default): convert but do not mention it in the tool result. "
        "enabled: convert and note the conversion in the tool result. "
        "disabled: never auto-convert."
    ),
)
REGISTRY["system.channels.slack.enabled"] = ParamSpec(
    name="system.channels.slack.enabled",
    value_type="boolean",
    scope="global",
    default=False,
    description=(
        "Enable the Slack channel integration. "
        "When true, the Slack Socket Mode client is started on server boot "
        "if the required tokens are present. "
        "When false (default for unset), Slack integration is skipped entirely regardless of token availability."
    ),
)
REGISTRY["desktop.slbp-process.clear-logs-on-start"] = ParamSpec(
    name="desktop.slbp-process.clear-logs-on-start",
    value_type="boolean",
    scope="global",
    default=False,
    description=(
        "When true, truncate .slbp-server.log at the start of every server boot launched "
        "by the desktop app (`slbp server run --desktop`). "
        "When false (default for unset), the log file keeps growing across restarts. "
        "Has no effect on a server started directly from a terminal -- that invocation "
        "never writes to .slbp-server.log in the first place (the desktop app owns the "
        "redirection to that file)."
    ),
)

def validate_registry_defaults() -> None:
    """Server-start sanity check: every registered param must declare a default.

    ParamSpec.default has no pydantic-level fallback, so constructing a spec without
    an explicit `default=` already raises at import time -- but that only catches the
    *first* offender and stops there. This walks the fully-built REGISTRY and reports
    every offender at once, which is more useful if this check is ever loosened or a
    spec is ever built by some other path (e.g. ``ParamSpec.model_construct``, which
    bypasses validation entirely).

    Uses hasattr() rather than a truthiness/None check: None is a valid, intentional
    default for "omittable" params (request_extra_params, override_strict_tool_def,
    the *.model.name overrides, etc.) -- the failure this guards against is a spec that
    never got a `default` attribute at all, not one whose default happens to be falsy.
    """
    missing = sorted(name for name, spec in REGISTRY.items() if not hasattr(spec, "default"))
    if missing:
        raise RuntimeError(
            "param_registry: the following params are missing a required 'default': "
            + ", ".join(missing)
        )


# Enforced eagerly at import time (in addition to pydantic's own required-field
# validation during REGISTRY construction above) so that ANY entrypoint that imports
# this module -- server, CLI, tests -- is protected, not just the server startup path.
validate_registry_defaults()

# ---------------------------------------------------------------------------
# Derived sets (backward-compatible exports)
# ---------------------------------------------------------------------------

def param_storage_key(name: str, profile_prefix: str | None = None) -> str:
    """Return the kv_store key where this param's value lives.

    For global-scope params:  ``params.<name>``
    For profile-scope params: ``<profile_prefix>params.<name>``
    """
    if name not in REGISTRY:
        raise ValueError(f"Unknown param '{name}'")
    spec = REGISTRY[name]
    if spec.scope == "global":
        return f"params.{name}"
    if profile_prefix is None:
        raise ValueError(f"Param '{name}' is profile-scoped but no profile_prefix was given")
    return f"{profile_prefix}params.{name}"


GLOBAL_PARAMS: frozenset[str] = frozenset(
    name for name, spec in REGISTRY.items() if spec.scope == "global"
)

ALLOWED_PARAMS: frozenset[str] = frozenset(REGISTRY)
SYSTEM_ONLY_PARAMS: frozenset[str] = frozenset(
    name for name, spec in REGISTRY.items() if spec.system_only
)


def parse_param_value(name: str, raw: Any) -> Any:
    """Parse and validate a param value by name. Raises ValueError on failure."""
    if name not in REGISTRY:
        raise ValueError(
            f"Unknown param '{name}'. Allowed: {', '.join(sorted(ALLOWED_PARAMS))}"
        )
    return REGISTRY[name].parse_value(raw)
