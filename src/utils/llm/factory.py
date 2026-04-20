from __future__ import annotations

import logging

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.llm.streaming import StreamingLLM

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
        active_token = kv.get_value("active_token")
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

        model = kv.get_value("model") or None
        param_keys = kv.list_keys(prefix="params.")
        model_params = {
            k[len("params.model."):]: kv.get_value(k)
            for k in param_keys if k.startswith("params.model.")
        }
        extra = model_params.pop("request_extra_params", None)
        if extra:
            model_params.update(extra)
        # These model.* params control internal call budgets, not the LLM API itself.
        # Pop them from model_params (so they don't leak into API request payloads)
        # and surface them via system_params where callers can read them.
        compaction_max_tokens = model_params.pop("compaction_max_tokens", None)
        watchdog_max_tokens = model_params.pop("watchdog_max_tokens", None)
        title_summary_max_tokens = model_params.pop("title_summary_max_tokens", None)
        system_params = {
            k[len("params.system."):]: kv.get_value(k)
            for k in param_keys if k.startswith("params.system.")
        }
        if compaction_max_tokens is not None:
            system_params["compaction_max_tokens"] = compaction_max_tokens
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
