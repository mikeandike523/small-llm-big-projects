"""
Single source of truth for all valid slbp param names.
Imported by both the CLI (param.py) and the LLM factory to filter DB keys.
"""

# All four sampler namespaces share the same five per-model param suffixes.
_SAMPLER_SUFFIXES: frozenset[str] = frozenset(
    {"temperature", "top_p", "top_k", "max_tokens", "request_extra_params"}
)

_SAMPLER_NAMESPACES: tuple[str, ...] = (
    "watchdog.model",
    "summarizer.model",
    "patchrewriter.model",
)

ALLOWED_PARAMS: frozenset[str] = frozenset(
    {
        # Main agentic loop
        "model.temperature",
        "model.top_p",
        "model.top_k",
        "model.max_tokens",
        "model.request_extra_params",
        "model.irat",
        # System / infra
        "system.return_value_max_chars",
        "system.blank_response_retries",
    }
    | {f"{ns}.{s}" for ns in _SAMPLER_NAMESPACES for s in _SAMPLER_SUFFIXES}
)

# model.irat is a session flag, not an API param — never forwarded to any LLM request.
SYSTEM_ONLY_PARAMS: frozenset[str] = frozenset({"model.irat"})
