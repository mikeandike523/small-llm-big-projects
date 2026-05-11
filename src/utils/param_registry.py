"""
Single source of truth for all valid slbp param names.
Imported by both the CLI (param.py) and the LLM factory to filter DB keys.
"""

ALLOWED_PARAMS: frozenset[str] = frozenset({
    "model.temperature",
    "model.top_p",
    "model.top_k",
    "model.max_tokens",
    "model.watchdog_max_tokens",
    "model.title_summary_max_tokens",
    "model.request_extra_params",
    "model.irat",
    "system.return_value_max_chars",
})

# Params that are valid to set but must NOT be forwarded to the LLM API request.
# factory.py pops these before building model_params.
EXCLUDE_FROM_REQUEST: frozenset[str] = frozenset({
    "model.watchdog_max_tokens",
    "model.title_summary_max_tokens",
    "model.request_extra_params",
    "model.irat",
})
