from __future__ import annotations

import logging

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM
from src.utils.profile_utils import get_active_profile, _kv_prefix

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
        model_params = {
            k[len(full_model_prefix):]: kv.get_value(k)
            for k in param_keys if k.startswith(full_model_prefix)
        }
        extra = model_params.pop("request_extra_params", None)
        if extra:
            model_params.update(extra)
        # These model.* params control internal call budgets, not the LLM API itself.
        # Pop them from model_params (so they don't leak into API request payloads)
        # and surface them via system_params where callers can read them.
        watchdog_max_tokens = model_params.pop("watchdog_max_tokens", None)
        title_summary_max_tokens = model_params.pop("title_summary_max_tokens", None)
        system_params = {
            k[len(full_system_prefix):]: kv.get_value(k)
            for k in param_keys if k.startswith(full_system_prefix)
        }
        if watchdog_max_tokens is not None:
            system_params["watchdog_max_tokens"] = watchdog_max_tokens
        if title_summary_max_tokens is not None:
            system_params["title_summary_max_tokens"] = title_summary_max_tokens

    if not token_value or not endpoint_url:
        return None

    return {
        "endpoint_url": endpoint_url,
        "token_value": token_value,
        "model": model,
        "model_params": model_params,
        "system_params": system_params,
    }


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
    return StreamingLLM(
        config["endpoint_url"],
        config["token_value"],
        timeout_s,
        config["model"],
        config["model_params"],
    )
