from __future__ import annotations

import logging

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.utils.llm.dialect import detect_dialect, get_adapter
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.utils.param_registry import (
    ALLOWED_PARAMS as _ALLOWED_PARAMS,
    SYSTEM_ONLY_PARAMS as _SYSTEM_ONLY_PARAMS,
)

logger = logging.getLogger(__name__)


def _build_namespace_params(param_keys: list[str], full_prefix: str, kv: KVManager) -> dict:
    """Build a self-contained API params dict for one sampler namespace.

    Reads all stored keys under full_prefix, then merges request_extra_params on
    top (within the same namespace only). Returns a flat dict where max_tokens is
    a plain key alongside temperature/top_p/top_k. Callers extract max_tokens
    separately when invoking .fetch().
    """
    params: dict = {}
    for k in param_keys:
        if not k.startswith(full_prefix):
            continue
        suffix = k[len(full_prefix):]
        if suffix == "request_extra_params":
            continue  # handled below after base params are collected
        params[suffix] = kv.get_value(k)
    extra_key = full_prefix + "request_extra_params"
    if extra_key in param_keys:
        extra = kv.get_value(extra_key) or {}
        params.update(extra)  # merges on top within this namespace only
    return params


def load_llm_config(profile_name: str | None = None) -> dict | None:
    """
    Read token, endpoint, model, and params from the DB for the given profile.
    If profile_name is None, reads the system-wide active profile.
    Returns a dict with keys:
        endpoint_url, token_value, provider, model,
        model_params,        -- forwarded to main streaming calls
        watchdog_params,     -- used by all YES/NO and short-answer samplers
        summarizer_params,   -- used by compaction and summarize_memory_item
        patchrewriter_params,-- used by the patch-fix retry sampler
        system_params        -- internal flags (irat, return_value_max_chars)
    Returns None if no active token/endpoint is configured.
    """
    try:
        pool = get_pool()
    except Exception as exc:
        logger.warning("DB pool error: %s", exc)
        return None

    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = profile_name if profile_name is not None else get_active_profile(kv)
        if not profile:
            return None
        prefix = _kv_prefix(profile)

        active_token = kv.get_value(prefix + "active_token")
        if not active_token:
            return None

        provider = active_token["provider"]
        token_name = active_token.get("name", "")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_value, endpoint_url
                FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, token_name),
            )
            row = cursor.fetchone()

        if not row:
            return None

        token_value, endpoint_url = row

        if not endpoint_url:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT default_endpoint_url
                    FROM known_providers
                    WHERE BINARY provider_key = BINARY %s
                    LIMIT 1
                    """,
                    (provider,),
                )
                kp_row = cursor.fetchone()
            endpoint_url = kp_row[0] if kp_row else None

        model = kv.get_value(prefix + "model") or None
        full_params_prefix = prefix + "params."
        full_model_prefix = prefix + "params.model."
        param_keys = kv.list_keys(prefix=full_params_prefix)

        # Main model params: all model.* keys that are allowed and not system-only,
        # with request_extra_params merged on top.
        model_params: dict = {}
        for k in param_keys:
            if not k.startswith(full_model_prefix):
                continue
            suffix = k[len(full_model_prefix):]
            full_name = f"model.{suffix}"
            if full_name not in _ALLOWED_PARAMS or full_name in _SYSTEM_ONLY_PARAMS:
                continue
            if suffix == "request_extra_params":
                continue  # merged below
            model_params[suffix] = kv.get_value(k)
        extra_key = full_model_prefix + "request_extra_params"
        if extra_key in param_keys:
            extra = kv.get_value(extra_key) or {}
            model_params.update(extra)

        # Per-sampler namespaces — each completely independent.
        watchdog_params = _build_namespace_params(
            param_keys, prefix + "params.watchdog.model.", kv
        )
        summarizer_params = _build_namespace_params(
            param_keys, prefix + "params.summarizer.model.", kv
        )
        patchrewriter_params = _build_namespace_params(
            param_keys, prefix + "params.patchrewriter.model.", kv
        )

        # System-only flags (never forwarded to any LLM API).
        system_params: dict = {}
        system_prefix = prefix + "params.system."
        for k in param_keys:
            if k.startswith(system_prefix):
                system_params[k[len(system_prefix):]] = kv.get_value(k)
        irat_key = full_model_prefix + "irat"
        if irat_key in param_keys:
            system_params["irat"] = kv.get_value(irat_key)

    if not token_value or not endpoint_url:
        return None

    return {
        "endpoint_url": endpoint_url,
        "token_value": token_value,
        "provider": provider,
        "model": model,
        "model_params": model_params,
        "watchdog_params": watchdog_params,
        "summarizer_params": summarizer_params,
        "patchrewriter_params": patchrewriter_params,
        "system_params": system_params,
    }


def _call_sampler(
    llm: StreamingLLM,
    messages: list[dict],
    sampler_params: dict,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
):
    """Invoke llm.fetch() with a sampler params dict.

    max_tokens is extracted and passed as a kwarg; the remaining keys are
    forwarded as the parameters dict (API params like temperature/top_p/top_k,
    plus any extra keys merged in from request_extra_params).
    on_usage(usage_dict) is called if provided and the response carries usage data.
    on_request_log(sampler_params) is called before the fetch to log the outgoing params.
    on_reasoning_detected(reasoning_len) is called if the response contains reasoning tokens.
    """
    max_tokens = sampler_params.get("max_tokens")
    api_params = {k: v for k, v in sampler_params.items() if k != "max_tokens"}

    if on_request_log is not None:
        try:
            on_request_log(sampler_params)
        except Exception:
            pass

    result = llm.fetch(messages, max_tokens=max_tokens, parameters=api_params)

    if on_reasoning_detected is not None and result.reasoning:
        try:
            on_reasoning_detected(len(result.reasoning))
        except Exception:
            pass

    if on_usage is not None and result.usage is not None:
        try:
            on_usage(result.usage)
        except Exception:
            pass
    return result


def make_llm_from_config(
    config: dict,
    timeout_s: float | None = None,
    config_loader=None,
) -> StreamingLLM:
    """
    Create a StreamingLLM from an already-loaded config dict (as returned by
    load_llm_config). Avoids a second DB round-trip when the caller already
    has the config in hand. Caller must check config is not None before calling.
    Pass config_loader to enable per-exchange config refresh.
    """
    dialect = detect_dialect(
        provider=config.get("provider"),
        endpoint_url=config.get("endpoint_url"),
        model=config.get("model"),
    )
    adapter = get_adapter(dialect)
    return StreamingLLM(
        config["endpoint_url"],
        config["token_value"],
        timeout_s,
        config["model"],
        config["model_params"],
        adapter=adapter,
        config_loader=config_loader,
    )


def make_llm_refreshing(
    timeout_s: float | None = None,
    profile_name: str | None = None,
) -> StreamingLLM:
    """
    Create a StreamingLLM that reloads its config from the DB on every stream()/fetch() call.
    If profile_name is given, that profile is used for every reload (session-level override).
    Raises RuntimeError if no active config is found at construction time.
    """
    config = load_llm_config(profile_name)
    if config is None:
        raise RuntimeError("No active token/endpoint configured.")
    loader = (lambda: load_llm_config(profile_name)) if profile_name else load_llm_config
    return make_llm_from_config(config, timeout_s, config_loader=loader)


def make_llm(timeout_s: float | None = None) -> StreamingLLM | None:
    """
    Create a StreamingLLM instance from the currently active DB config.
    Returns None if no active token/endpoint is configured.

    timeout_s overrides the default request timeout; pass a small value
    (e.g. HANG_DECISION_TIMEOUT) for out-of-band decision calls.
    """
    config = load_llm_config()
    if config is None:
        return None
    dialect = detect_dialect(
        provider=config.get("provider"),
        endpoint_url=config.get("endpoint_url"),
        model=config.get("model"),
    )
    adapter = get_adapter(dialect)
    return StreamingLLM(
        config["endpoint_url"],
        config["token_value"],
        timeout_s,
        config["model"],
        config["model_params"],
        adapter=adapter,
    )
