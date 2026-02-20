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

    lines.append(f"Response Status: {status_code if status_code is not None else '(no response)'}")
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
