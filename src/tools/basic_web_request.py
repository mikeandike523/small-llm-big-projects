import json
import os
from typing import Any

import httpx

from src.utils.http.helpers import (
    apply_service_tokens_to_headers,
    ensure_session_memory,
    format_response,
    is_json_content_type,
    load_latest_service_tokens_from_db,
    validate_string_list,
)
from src.utils.sql.kv_manager import KVManager
from src.data import get_pool


LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 800

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
                    "anyOf": [{"type": "string"}, {"type": "object"}],
                    "description": (
                        "Optional body data. Can be a plain string or an object. "
                        "If content_type is JSON-like (e.g. application/json), "
                        "objects are automatically serialized to JSON. "
                        "Pass a raw string for exact body control."
                    ),
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
                        "for example, Authorization: Bearer service_token:<provider_name>. "
                        "If exactly one token is loaded and no Authorization header is provided, "
                        "Authorization: Bearer <token> is applied automatically."
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


def needs_approval(args: dict) -> bool:
    return False


def execute(args, session_data):
    url: str = args["url"]
    content_type: str = args["content_type"]
    accept: str = args["accept"]
    method: str = args["method"]
    timeout: int = args["timeout"]

    headers: dict[str, str] = (args.get("headers") or {}).copy()
    body: str | dict | None = args.get("body")

    if isinstance(body, dict):
        if is_json_content_type(content_type):
            body = json.dumps(body)
        else:
            return "Error: 'body' is an object but content_type is not JSON-like. Pass a string body or use a JSON content type."
    debug_show_bad_json: bool = bool(args.get("debug_show_bad_json", False))

    target = args.get("target", "return_value")

    try:
        load_service_tokens = validate_string_list(
            args.get("load_service_tokens"), "load_service_tokens"
        )
    except ValueError as e:
        return f"Error: {e}"

    if load_service_tokens:
        try:
            tokens, missing = load_latest_service_tokens_from_db(load_service_tokens)
        except Exception as e:
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

        headers = apply_service_tokens_to_headers(headers, tokens)

        if len(tokens) == 1 and not any(k.lower() == "authorization" for k in headers):
            headers["Authorization"] = f"Bearer {next(iter(tokens.values()))}"

    if target in ("session_memory", "project_memory") and not args.get("memory_key"):
        return "Error: 'memory_key' is required when target is 'session_memory' or 'project_memory'."

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
                request_kwargs["content"] = body.encode("utf-8")

            resp = client.request(method=method, url=url, **request_kwargs)

        status_code = resp.status_code
        resp_ct = resp.headers.get("content-type")
        resp_text = resp.text

        if is_json_content_type(accept):
            try:
                resp_json = resp.json()
            except Exception as e:
                json_error = f"{type(e).__name__}: {e}"
                if not debug_show_bad_json:
                    resp_text = None

        if is_json_content_type(accept):
            result = format_response(
                status_code=status_code,
                response_content_type=resp_ct,
                accept=accept,
                json_value=resp_json,
                text_value=resp_text if (resp_json is None and debug_show_bad_json) else None,
                json_error=json_error,
            )
        else:
            result = format_response(
                status_code=status_code,
                response_content_type=resp_ct,
                accept=accept,
                text_value=resp_text,
            )

    except Exception as e:
        result = format_response(
            status_code=None,
            response_content_type=None,
            accept=accept,
            json_error=f"Request failed: {type(e).__name__}: {e}",
        )

    if target == "return_value":
        return result

    memory_key = args["memory_key"]

    if target == "session_memory":
        if session_data is None:
            session_data = {}
        memory = ensure_session_memory(session_data)
        memory[memory_key] = result
        return f"Response data written to session memory item {memory_key}"

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, result)
            conn.commit()
        return f"Response data written to project memory item {memory_key}"

    return result
