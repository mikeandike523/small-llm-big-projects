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
from src.tools._web_search_filter import web_search_filter
from src.tools._web_search_extractor import _condense_with_llm


_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_ACCEPT = "application/json"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; slbp-agent/1.0; +https://github.com/mikeandike523/small-llm-big-projects)"
)
# Current web filters are designed for this version
"""
See:

https://api-dashboard.search.brave.com/documentation/services/web-search
#:~:text=API%20Sports.-,Changelog,-This%20changelog%20outlines
"""


LEAVE_OUT = "SHORT"
NO_STUB = True
TOOL_SHORT_AMOUNT = 8192

DEFAULT_TIMEOUT = 90   # seconds; Brave rate limits can cause slow responses
MAX_TIMEOUT = 180      # seconds; tool also makes an out-of-band LLM call
TIMEOUT_HINT = None

MAX_EXTRACTION_TRIES = 3
DEFAULT_COUNT = 5

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "brave_web_search",
        "description": (
            "Search the web using the Brave Search API. "
            "Requires a 'brave' service token to be configured "
            "(set one with: service-token set brave <your-token>)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "count": {
                    "type": "integer",
                    "description": f"Number of results to return (1–20). Defaults to {DEFAULT_COUNT}.",
                    "minimum": 1,
                    "maximum": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Zero-based page offset (0–9). Defaults to 0.",
                    "minimum": 0,
                    "maximum": 9,
                },
                "freshness": {
                    "type": "string",
                    "description": (
                        "Limit results by recency: "
                        "'pd' (past day), 'pw' (past week), "
                        "'pm' (past month), 'py' (past year)."
                    ),
                    "enum": ["pd", "pw", "pm", "py"],
                },
                "country": {
                    "type": "string",
                    "description": "2-letter country code to bias results (e.g. 'US', 'GB').",
                },
                # Default en, as most llms are primarily English-trained
                "search_lang": {
                    "type": "string",
                    "description": "Language code for results (e.g. 'en', 'fr'). Defaults to 'en' if not specified.",
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "Where to send the results. "
                        "'return_value' (default) returns directly. "
                        "'session_memory' writes to a session memory key. "
                        "'project_memory' writes to a project memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write results to. "
                        "Required when target is 'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": ["query"],
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

    query: str = args["query"]
    count: int = args.get("count", DEFAULT_COUNT)
    offset: int = args.get("offset", 0)
    freshness: str | None = args.get("freshness")
    country: str | None = args.get("country")
    search_lang: str | None = args.get("search_lang", 'en')
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

    params: dict[str, Any] = {"q": query, "count": count, "offset": offset}
    if freshness:
        params["freshness"] = freshness
    if country:
        params["country"] = country
    if search_lang:
        params["search_lang"] = search_lang

    params["result_filter"] = [
        "query",
        "web",
        "news",
        "discussions",
        "faq",
    ]

    headers = {
        "Accept": _ACCEPT,
        "X-Subscription-Token": tokens["brave"],
        "User-Agent": _USER_AGENT
    }

    if on_chunk:
        on_chunk("Searching Brave...")

    status_code: int | None = None
    resp_ct: str | None = None
    resp_json: Any | None = None
    json_error: str | None = None

    try:
        with httpx.Client(follow_redirects=True, timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(_BRAVE_SEARCH_URL, params=params, headers=headers)

        status_code = resp.status_code
        resp_ct = resp.headers.get("content-type")

        try:
            resp_json = resp.json()
        except Exception as e:
            json_error = f"{type(e).__name__}: {e}"

    except httpx.TimeoutException:
        from src.utils.exceptions import ToolTimeoutError
        raise ToolTimeoutError("brave_web_search", DEFAULT_TIMEOUT)
    except Exception as e:
        return format_response(
            status_code=None,
            response_content_type=None,
            accept=_ACCEPT,
            json_error=f"Request failed: {type(e).__name__}: {e}",
        )

    if resp.status_code == 200 and resp_json is not None:
        # Pre-filter to remove known noise (thumbnails, favicons, etc.) before
        # feeding to the LLM, reducing context size.
        filtered = web_search_filter(resp_json) if isinstance(resp_json, dict) else resp_json

        if on_chunk:
            on_chunk("\nCondensing results with LLM...")

        condensed = _condense_with_llm(filtered, query, max_tries=MAX_EXTRACTION_TRIES, on_chunk=on_chunk) if isinstance(filtered, dict) else None
        if condensed is not None:
            result = json.dumps({"results": condensed}, ensure_ascii=False, indent=2)
        else:
            # Fallback: return the pre-filtered raw JSON
            result = json.dumps(filtered, ensure_ascii=False, indent=2)
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
        return f"Brave search results written to session memory item {memory_key!r}"

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, result)
            conn.commit()
        return f"Brave search results written to project memory item {memory_key!r}"

    return result
