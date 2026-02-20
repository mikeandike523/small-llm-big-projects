import os
import json
from typing import Any

import httpx

from src.utils.sql.kv_manager import KVManager
from src.data import get_pool


DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "basic_web_request",
        "description": "Make a basic http or https request",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The url to request"},
                "content_type": {
                    "type": "string",
                    "description": "The MIME content type of the request.",
                },
                "accept": {
                    "type": "string",
                    "description": "The expected MIME content type of the response.",
                },
                "method": {
                    "type": "string",
                    "description": "The HTTP method",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                },
                "headers": {
                    "type": "object",
                    "description": "Optional HTTP headers as key-value pairs",
                    "additionalProperties": {"type": "string"},
                },
                "body": {
                    "type": "string",
                    "description": "Optional body data. Use stringified JSON for JSON requests.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "The request time limit, in seconds. Must be at least 5",
                    "minimum": 5,
                },
                "debug_show_bad_json": {
                    "type": "boolean",
                    "description": (
                        "If the response content type is expected to be JSON, "
                        "but the response body is not valid JSON, "
                        "show the response body text instead of an error message. "
                        "If debug_show_bad_json is true, it is recommended to "
                        "set the target parameter to session_memory "
                        "so it can be read in chunks by other tools."
                    ),
                },
                "load_service_tokens": {
                    "type": "array",
                    "description": (
                        "A list of service tokens (categorized by provider name) "
                        "to load for this request. "
                        "Use a service token in header item values, using the special "
                        "syntax service_token:<provider_name> "
                        "for example, Authorization: Bearer service_token:<provider_name>"
                    ),
                    "items": {"type": "string"},
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "Where to send the file contents. "
                        "'return_value' (default) returns the contents directly. "
                        "'session_memory' writes the contents to a session memory key. "
                        "'project_memory' writes the contents to a project memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the file contents to. "
                        "Required when target is 'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": ["url", "content_type", "accept", "method", "timeout"],
            "additionalProperties": False,
        },
    },
}


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def is_json_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False

    media_type = content_type.split(";")[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def _format_response(
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


def _validate_string_list(value: Any, field_name: str) -> list[str] | None:
    """Validate that value is either None or a list[str]."""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"'{field_name}' must be an array of strings.")
    return value


def _load_latest_service_tokens_from_db(providers: list[str]) -> tuple[dict[str, str], list[str]]:
    """
    Load the *most recently created* token for each provider.

    Returns:
      (tokens_by_provider, missing_providers)

    Missing providers means the query succeeded, but no token rows were found
    for those providers.

    Expected table shape (minimum):
      - provider VARCHAR(64)
      - value TEXT
      - created_at TIMESTAMP (or DATETIME)

    If your table doesn't have created_at but does have an auto-increment id,
    you can replace ORDER BY created_at DESC with ORDER BY id DESC.
    """
    if not providers:
        return {}, []

    # De-duplicate but keep deterministic order
    providers_unique = list(dict.fromkeys([p.strip() for p in providers if p and p.strip()]))
    if not providers_unique:
        return {}, []

    placeholders = ", ".join(["%s"] * len(providers_unique))

    # MySQL 8+ window function approach (recommended)
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

    # Any exception here is considered a "failed to load" (DB down, bad schema, etc.)
    with pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(providers_unique))
            for provider, token_value in cur.fetchall():
                tokens[str(provider)] = str(token_value)

    missing = [p for p in providers_unique if p not in tokens]
    return tokens, missing


def _apply_service_tokens_to_headers(
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


def execute(args, session_data):
    url: str = args["url"]
    content_type: str = args["content_type"]
    accept: str = args["accept"]
    method: str = args["method"]
    timeout: int = args["timeout"]

    headers: dict[str, str] = (args.get("headers") or {}).copy()
    body: str | None = args.get("body")
    debug_show_bad_json: bool = bool(args.get("debug_show_bad_json", False))

    target = args.get("target", "return_value")

    # NEW: Validate + load + apply service tokens to header values
    try:
        load_service_tokens = _validate_string_list(
            args.get("load_service_tokens"), "load_service_tokens"
        )
    except ValueError as e:
        return f"Error: {e}"

    if load_service_tokens:
        # Load most recently created token per provider.
        try:
            tokens, missing = _load_latest_service_tokens_from_db(load_service_tokens)
        except Exception as e:
            # Differentiate "failed to load" (DB/query failure) from "missing provider"
            return (
                "Error: Failed to load service tokens due to "
                f"{type(e).__name__}: {e}"
            )

        if missing:
            missing_list = ", ".join(missing)
            return (
                "Error: No service token found for provider(s): "
                f"{missing_list}. "
                "Create one with your service-token set command."
            )

        headers = _apply_service_tokens_to_headers(headers, tokens)

    # Enforce memory_key presence when required
    if target in ("session_memory", "project_memory") and not args.get("memory_key"):
        return "Error: 'memory_key' is required when target is 'session_memory' or 'project_memory'."

    # Ensure Content-Type / Accept are set (allow explicit override by caller)
    headers.setdefault("Content-Type", content_type)
    headers.setdefault("Accept", accept)

    status_code: int | None = None
    resp_ct: str | None = None
    resp_text: str | None = None
    resp_json: Any | None = None
    json_error: str | None = None

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            request_kwargs: dict[str, Any] = {"headers": headers}

            if body is not None:
                # Assume utf-8; user requested to keep it simple
                request_kwargs["content"] = body.encode("utf-8")

            resp = client.request(method=method, url=url, **request_kwargs)

        status_code = resp.status_code
        resp_ct = resp.headers.get("content-type")
        resp_text = resp.text

        # Only attempt JSON parse when accept is json-like (per your rule)
        if is_json_content_type(accept):
            try:
                resp_json = resp.json()
            except Exception as e:
                json_error = f"{type(e).__name__}: {e}"
                if debug_show_bad_json:
                    # Keep resp_text for output under Response text
                    pass
                else:
                    # Hide response body; show structured error instead
                    resp_text = None

        # Format output according to rules
        if is_json_content_type(accept):
            result = _format_response(
                status_code=status_code,
                response_content_type=resp_ct,
                accept=accept,
                json_value=resp_json,
                text_value=resp_text if (resp_json is None and debug_show_bad_json) else None,
                json_error=json_error,
            )
        else:
            result = _format_response(
                status_code=status_code,
                response_content_type=resp_ct,
                accept=accept,
                text_value=resp_text,
            )

    except Exception as e:
        # Network / timeout / DNS / etc.
        result = _format_response(
            status_code=None,
            response_content_type=None,
            accept=accept,
            json_value=None,
            text_value=None,
            json_error=f"Request failed: {type(e).__name__}: {e}",
        )

    # Route output
    if target == "return_value":
        return result

    memory_key = args["memory_key"]

    if target == "session_memory":
        if session_data is None:
            session_data = {}
        memory = _ensure_session_memory(session_data)
        memory[memory_key] = result
        return f"Response data written to session memory item {memory_key}"

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, result)
            conn.commit()
        return f"Response data written to project memory item {memory_key}"

    # Fallback (should be unreachable due to enum)
    return result
