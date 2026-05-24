from __future__ import annotations

import logging

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.utils.llm.dialect import detect_dialect, get_adapter
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.utils.param_registry import (
    ALLOWED_PARAMS as _ALLOWED_PARAMS,
    EXCLUDE_FROM_REQUEST as _EXCLUDE_FROM_REQUEST,
)

logger = logging.getLogger(__name__)


def load_llm_config() -> dict | None:
    """
    Read the active token, endpoint, model, and params from the DB.
    Returns a dict with keys: endpoint_url, token_value, model, model_params,
    system_params — or None if no active token/endpoint is configured.
    """
    try:
        pool = get_pool()
    except Exception as exc:
        logger.warning("DB pool error: %s", exc)
        return None

    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
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
        full_system_prefix = prefix + "params.system."
        param_keys = kv.list_keys(prefix=full_params_prefix)
        # Only include params that are allowed and not reserved for internal use.
        # EXCLUDE_FROM_REQUEST params are read separately into system_params below.
        model_params = {
            k[len(full_model_prefix) :]: kv.get_value(k)
            for k in param_keys
            if k.startswith(full_model_prefix)
            and f"model.{k[len(full_model_prefix):]}" in _ALLOWED_PARAMS
            and f"model.{k[len(full_model_prefix):]}" not in _EXCLUDE_FROM_REQUEST
        }
        extra_key = prefix + "params.model.request_extra_params"
        extra = kv.get_value(extra_key) if extra_key in param_keys else None
        if extra:
            model_params.update(extra)
        system_params = {
            k[len(full_system_prefix) :]: kv.get_value(k)
            for k in param_keys
            if k.startswith(full_system_prefix)
        }
        for param_name in _EXCLUDE_FROM_REQUEST:
            suffix = param_name[len("model.") :]
            full_key = full_model_prefix + suffix
            if full_key in param_keys:
                system_params[suffix] = kv.get_value(full_key)

    if not token_value or not endpoint_url:
        return None

    return {
        "endpoint_url": endpoint_url,
        "token_value": token_value,
        "provider": provider,
        "model": model,
        "model_params": model_params,
        "system_params": system_params,
    }


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


def make_llm_refreshing(timeout_s: float | None = None) -> StreamingLLM:
    """
    Create a StreamingLLM that reloads its config from the DB on every stream()/fetch() call.
    Use this for the main agent loop so profile/token switches take effect at the next exchange.
    Raises RuntimeError if no active config is found at construction time.
    """
    config = load_llm_config()
    if config is None:
        raise RuntimeError("No active token/endpoint configured.")
    return make_llm_from_config(config, timeout_s, config_loader=load_llm_config)


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
