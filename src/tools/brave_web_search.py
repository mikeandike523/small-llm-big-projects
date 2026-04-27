"""
API Documentation

https://api-dashboard.search.brave.com/documentation/services/llm-context
https://api-dashboard.search.brave.com/api-reference/summarizer/llm_context/post

"""

import json
import os
from typing import Any

import httpx

from src.utils.http.helpers import (
    ensure_session_memory,
    format_response,
    load_latest_service_tokens_from_db,
)
from src.utils.sql.kv_manager import KVManager
from src.data import get_pool


_BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
_ACCEPT = "application/json"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; slbp-agent/1.0; +https://github.com/mikeandike523/small-llm-big-projects)"
)


LEAVE_OUT = "SHORT"
NO_STUB = True
TOOL_SHORT_AMOUNT = 8192

DEFAULT_TIMEOUT = 30
TIMEOUT_HINT = None

DEFAULT_COUNTRY = "US"
DEFAULT_SEARCH_LANG = "en"
DEFAULT_COUNT = 20
DEFAULT_MAXIMUM_NUMBER_OF_URLS = 20
DEFAULT_MAXIMUM_NUMBER_OF_TOKENS = 8192
DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS = 50
DEFAULT_CONTEXT_THRESHOLD_MODE = "balanced"
DEFAULT_MAXIMUM_NUMBER_OF_TOKENS_PER_URL = 4096
DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS_PER_URL = 50

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "brave_llm_context",
        "description": (
            "Retrieve pre-extracted web content optimized for AI agents, LLM grounding, "
            "and RAG pipelines using Brave's LLM Context API. Returns grounding snippets "
            "and source metadata from a single search request. Requires a 'brave' service "
            "token to be configured (set one with: service-token set brave <your-token>)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "The user's search query. Must be non-empty, at most 400 characters, and at most 50 words.",
                    "minLength": 1,
                    "maxLength": 400,
                },
                "country": {
                    "type": "string",
                    "description": f"Two-character country code for search results. Defaults to {DEFAULT_COUNTRY!r}.",
                    "minLength": 2,
                    "maxLength": 2,
                    "default": DEFAULT_COUNTRY,
                },
                "search_lang": {
                    "type": "string",
                    "description": f"Language preference for search results. Use a 2+ character language code. Defaults to {DEFAULT_SEARCH_LANG!r}.",
                    "minLength": 2,
                    "default": DEFAULT_SEARCH_LANG,
                },
                "count": {
                    "type": "integer",
                    "description": f"Maximum number of search results to consider when selecting LLM context. Defaults to {DEFAULT_COUNT}; maximum is 50.",
                    "minimum": 1,
                    "maximum": 50,
                    "default": DEFAULT_COUNT,
                },
                "maximum_number_of_urls": {
                    "type": "integer",
                    "description": f"Maximum number of different URLs to include in the LLM context. Defaults to {DEFAULT_MAXIMUM_NUMBER_OF_URLS}; range is 1–50.",
                    "minimum": 1,
                    "maximum": 50,
                    "default": DEFAULT_MAXIMUM_NUMBER_OF_URLS,
                },
                "maximum_number_of_tokens": {
                    "type": "integer",
                    "description": f"Approximate maximum number of tokens to include in context. Defaults to {DEFAULT_MAXIMUM_NUMBER_OF_TOKENS}; range is 1024–32768.",
                    "minimum": 1024,
                    "maximum": 32768,
                    "default": DEFAULT_MAXIMUM_NUMBER_OF_TOKENS,
                },
                "maximum_number_of_snippets": {
                    "type": "integer",
                    "description": f"Maximum number of snippets/chunks to include across the LLM context. Defaults to {DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS}; range is 1–256.",
                    "minimum": 1,
                    "maximum": 256,
                    "default": DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS,
                },
                "context_threshold_mode": {
                    "type": "string",
                    "description": (
                        "Relevance threshold mode for including extracted content in context. "
                        f"Defaults to {DEFAULT_CONTEXT_THRESHOLD_MODE!r}. Use 'strict' for fewer, more relevant results; "
                        "'lenient' for broader recall; 'disabled' to include all extracted content."
                    ),
                    "enum": ["disabled", "strict", "balanced", "lenient"],
                    "default": DEFAULT_CONTEXT_THRESHOLD_MODE,
                },
                "maximum_number_of_tokens_per_url": {
                    "type": "integer",
                    "description": f"Maximum number of tokens to include per URL. Defaults to {DEFAULT_MAXIMUM_NUMBER_OF_TOKENS_PER_URL}; range is 512–8192.",
                    "minimum": 512,
                    "maximum": 8192,
                    "default": DEFAULT_MAXIMUM_NUMBER_OF_TOKENS_PER_URL,
                },
                "maximum_number_of_snippets_per_url": {
                    "type": "integer",
                    "description": f"Maximum number of snippets to include per URL. Defaults to {DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS_PER_URL}; range is 1–100.",
                    "minimum": 1,
                    "maximum": 100,
                    "default": DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS_PER_URL,
                },
                "freshness": {
                    "type": "string",
                    "description": (
                        "Optional page-age filter. Supported values are 'pd' (past 24 hours), "
                        "'pw' (past 7 days), 'pm' (past 31 days), 'py' (past 365 days), "
                        "or a custom range formatted as YYYY-MM-DDtoYYYY-MM-DD."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "Where to send the results. 'return_value' (default) returns directly. "
                        "'session_memory' writes to a session memory key. "
                        "'project_memory' writes to a project memory key."
                    ),
                    "default": "return_value",
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write results to. Required when target is "
                        "'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    on_chunk = (special_resources or {}).get("on_chunk")

    q: str = args["q"]
    target: str = args.get("target", "return_value")
    memory_key: str | None = args.get("memory_key")

    if target in ("session_memory", "project_memory") and not memory_key:
        return "Error: 'memory_key' is required when target is 'session_memory' or 'project_memory'."

    try:
        tokens, missing = load_latest_service_tokens_from_db(["brave"])
    except Exception as e:
        return f"Error: Failed to load 'brave' service token: {type(e).__name__}: {e}"

    if missing:
        return (
            "Error: No service token found for provider 'brave'. "
            "Add one with: service-token set brave <your-token>"
        )

    payload: dict[str, Any] = {
        "q": q,
        "country": args.get("country", DEFAULT_COUNTRY),
        "search_lang": args.get("search_lang", DEFAULT_SEARCH_LANG),
        "count": args.get("count", DEFAULT_COUNT),
        "spellcheck": True,
        "maximum_number_of_urls": args.get("maximum_number_of_urls", DEFAULT_MAXIMUM_NUMBER_OF_URLS),
        "maximum_number_of_tokens": args.get("maximum_number_of_tokens", DEFAULT_MAXIMUM_NUMBER_OF_TOKENS),
        "maximum_number_of_snippets": args.get("maximum_number_of_snippets", DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS),
        "context_threshold_mode": args.get("context_threshold_mode", DEFAULT_CONTEXT_THRESHOLD_MODE),
        "maximum_number_of_tokens_per_url": args.get(
            "maximum_number_of_tokens_per_url",
            DEFAULT_MAXIMUM_NUMBER_OF_TOKENS_PER_URL,
        ),
        "maximum_number_of_snippets_per_url": args.get(
            "maximum_number_of_snippets_per_url",
            DEFAULT_MAXIMUM_NUMBER_OF_SNIPPETS_PER_URL,
        ),
        # Localization / location-aware recall is intentionally disabled for now.
        # Future feature: when app location support exists, add X-Loc-* headers here and allow enable_local=True.
        "enable_local": False,
        "enable_source_metadata": False,
    }

    freshness: str | None = args.get("freshness")
    if freshness:
        payload["freshness"] = freshness

    headers = {
        "Accept": _ACCEPT,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
        "X-Subscription-Token": tokens["brave"],
        "User-Agent": _USER_AGENT,
    }

    if on_chunk:
        on_chunk("Retrieving Brave LLM context...")

    status_code: int | None = None
    resp_ct: str | None = None
    resp_json: Any | None = None
    json_error: str | None = None

    try:
        with httpx.Client(follow_redirects=True, timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(_BRAVE_LLM_CONTEXT_URL, json=payload, headers=headers)

        status_code = resp.status_code
        resp_ct = resp.headers.get("content-type")

        try:
            resp_json = resp.json()
        except Exception as e:
            json_error = f"{type(e).__name__}: {e}"

    except httpx.TimeoutException:
        from src.utils.exceptions import ToolTimeoutError
        raise ToolTimeoutError("brave_llm_context", DEFAULT_TIMEOUT)
    except Exception as e:
        return format_response(
            status_code=None,
            response_content_type=None,
            accept=_ACCEPT,
            json_error=f"Request failed: {type(e).__name__}: {e}",
        )

    if resp.status_code == 200 and resp_json is not None:
        result = json.dumps(resp_json, ensure_ascii=False, indent=2)
    else:
        result = format_response(
            status_code=status_code,
            response_content_type=resp_ct,
            accept=_ACCEPT,
            json_value=resp_json,
            json_error=json_error,
        )

    if target == "return_value":
        return result

    if target == "session_memory":
        memory = ensure_session_memory(session_data)
        memory[memory_key] = result
        return f"Brave LLM context results written to session memory item {memory_key!r}"

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, result)
            conn.commit()
        return f"Brave LLM context results written to project memory item {memory_key!r}"

    return result
