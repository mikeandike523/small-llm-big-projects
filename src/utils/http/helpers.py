import json
from typing import Any

from src.data import get_pool


def is_json_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False

    media_type = content_type.split(";")[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def format_response(
    *,
    status_code: int | None,
    response_content_type: str | None,
    accept: str,
    json_value: Any | None = None,
    text_value: str | None = None,
    json_error: str | None = None,
) -> str:
    ct_line = response_content_type if response_content_type else "(not set)"
    lines: list[str] = []

    lines.append(
        f"Response Status: {status_code if status_code is not None else '(no response)'}"
    )
    lines.append("")
    lines.append(f"Response Content Type: {ct_line}")
    lines.append("")

    if is_json_content_type(accept):
        lines.append("Response JSON:")
        if json_value is not None:
            lines.append(json.dumps(json_value, indent=2, ensure_ascii=False))
        else:
            err = json_error or "Invalid JSON in response body"
            lines.append(json.dumps({"error": err}, indent=2, ensure_ascii=False))

        if text_value is not None:
            lines.append("")
            lines.append("Response text:")
            lines.append(text_value)
    else:
        lines.append("Response text:")
        lines.append(text_value or "")

    return "\n".join(lines)


def validate_string_list(value: Any, field_name: str) -> list[str] | None:
    """Validate that value is either None or a list[str]."""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"'{field_name}' must be an array of strings.")
    return value


def load_latest_service_tokens_from_db(providers: list[str]) -> tuple[dict[str, str], list[str]]:
    """
    Load the most recently created token for each provider.

    Returns:
      (tokens_by_provider, missing_providers)

    Missing providers means the query succeeded, but no token rows were found
    for those providers.
    """
    if not providers:
        return {}, []

    providers_unique = list(dict.fromkeys([p.strip() for p in providers if p and p.strip()]))
    if not providers_unique:
        return {}, []

    placeholders = ", ".join(["%s"] * len(providers_unique))

    sql = f"""
        SELECT provider, value
        FROM (
            SELECT
                provider,
                value,
                ROW_NUMBER() OVER (
                    PARTITION BY provider
                    ORDER BY created_at DESC
                ) AS rn
            FROM service_tokens
            WHERE provider IN ({placeholders})
        ) t
        WHERE rn = 1
    """

    pool = get_pool()
    tokens: dict[str, str] = {}

    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(providers_unique))
            for provider, token_value in cur.fetchall():
                tokens[str(provider)] = str(token_value)

    missing = [p for p in providers_unique if p not in tokens]
    return tokens, missing


def apply_service_tokens_to_headers(
    headers: dict[str, str],
    tokens: dict[str, str],
) -> dict[str, str]:
    """Replace occurrences of 'service_token:<provider>' inside header values."""
    out = headers.copy()

    for hk, hv in out.items():
        if not isinstance(hv, str) or "service_token:" not in hv:
            continue

        new_val = hv
        for provider, token_value in tokens.items():
            needle = f"service_token:{provider}"
            if needle in new_val:
                new_val = new_val.replace(needle, token_value)

        out[hk] = new_val

    return out


def ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory
