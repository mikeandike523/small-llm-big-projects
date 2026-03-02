from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

import httpx

from src.utils.http.helpers import ensure_session_memory
from src.utils.sql.kv_manager import KVManager
from src.data import get_pool
from src.utils.exceptions import ToolTimeoutError


LEAVE_OUT = "SHORT"
TOOL_SHORT_AMOUNT = 1000

DEFAULT_TIMEOUT = 15  # seconds

# Wikipedia asks for a descriptive User-Agent identifying the tool.
_USER_AGENT = "slbp-agent/1.0 (https://github.com/slbp; open-source LLM assistant)"

# Modes and their Action API params
_MODE_PARAMS = {
    # Short plain-text intro paragraph(s) only
    "intro": {"prop": "extracts", "exintro": "true", "explaintext": "true"},
    # Full plain-text article
    "full":  {"prop": "extracts", "explaintext": "true"},
}

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "wikipedia",
        "description": (
            "Fetch a Wikipedia article as clean plain text via the Wikimedia API. "
            "Accepts either a raw Wikipedia URL (any language, desktop or mobile) "
            "or a bare article title. "
            "Use mode='intro' for a quick summary, 'full' for the complete article. "
            "No API key required. Pairs well with brave_web_search: when a search result "
            "links to a Wikipedia page, pass that URL directly to this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url_or_title": {
                    "type": "string",
                    "description": (
                        "Either a Wikipedia URL (e.g. 'https://en.wikipedia.org/wiki/Python_(programming_language)' "
                        "or 'https://en.m.wikipedia.org/wiki/...') "
                        "or a bare article title (e.g. 'Python (programming language)'). "
                        "When a URL is given the language and title are extracted automatically."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["intro", "full"],
                    "description": (
                        "'intro' (default): the opening section only — fast and concise. "
                        "'full': the complete article as plain text. "
                        "Use 'full' with target='session_memory' for large articles."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Wikipedia language code (default 'en'). "
                        "Ignored when a URL is supplied — the language is taken from the URL's hostname instead."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory", "project_memory"],
                    "description": (
                        "Where to send the article text. "
                        "'return_value' (default) returns it directly. "
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
                "timeout": {
                    "type": "integer",
                    "description": f"Request timeout in seconds (default {DEFAULT_TIMEOUT}, max 60).",
                    "minimum": 5,
                    "maximum": 60,
                },
            },
            "required": ["url_or_title"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_url(raw: str) -> tuple[str, str] | None:
    """
    Parse a Wikipedia URL and return (lang, title) or None if not a Wikipedia URL.

    Handles:
      https://en.wikipedia.org/wiki/Article_Title
      https://en.m.wikipedia.org/wiki/Article_Title
      https://de.wikipedia.org/wiki/Artikel
    """
    try:
        u = urlparse(raw)
        host = u.hostname or ""
        # Match <lang>.wikipedia.org or <lang>.m.wikipedia.org
        parts = host.split(".")
        if len(parts) >= 3 and parts[-2] == "wikipedia" and parts[-1] == "org":
            lang = parts[0] if parts[0] != "m" else parts[1]  # handle m.wikipedia.org edge case
            path = u.path  # e.g. /wiki/Python_(programming_language)
            if path.startswith("/wiki/"):
                title = unquote(path[len("/wiki/"):])
                if title:
                    return lang, title
    except Exception:
        pass
    return None


def _build_api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _fetch_article(
    lang: str,
    title: str,
    mode: str,
    timeout: int,
) -> str:
    """
    Call the Wikipedia Action API and return the article text.
    Returns a string that is either the article content or an "Error: ..." message.
    """
    params: dict = {
        "action": "query",
        "titles": title,
        "format": "json",
        "redirects": "1",  # follow redirects automatically
        **_MODE_PARAMS[mode],
    }

    api_url = _build_api_url(lang)
    headers = {"User-Agent": _USER_AGENT}

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(api_url, params=params, headers=headers)
    except httpx.TimeoutException:
        raise ToolTimeoutError("wikipedia", timeout)
    except Exception as e:
        return f"Error: Request to Wikipedia API failed: {type(e).__name__}: {e}"

    if resp.status_code != 200:
        return f"Error: Wikipedia API returned HTTP {resp.status_code}."

    try:
        data = resp.json()
    except Exception as e:
        return f"Error: Could not parse Wikipedia API response: {e}"

    # Navigate to the pages dict
    pages: dict = data.get("query", {}).get("pages", {})
    if not pages:
        return "Error: Wikipedia API returned no pages."

    # The API returns a dict keyed by page ID; there's always exactly one entry here.
    page = next(iter(pages.values()))

    # page ID of -1 means the article was not found.
    if page.get("pageid", -1) == -1 or "missing" in page:
        return (
            f"Error: Wikipedia article not found: {title!r} (language: {lang!r}). "
            "Check spelling or try a different title/URL."
        )

    extract: str = page.get("extract", "").strip()
    if not extract:
        return (
            f"Error: Wikipedia returned an empty extract for {title!r}. "
            "The article may be a redirect stub or have no text content."
        )

    resolved_title: str = page.get("title", title)
    header = f"Wikipedia: {resolved_title} (lang={lang}, mode={mode})"
    return f"{header}\n{'=' * len(header)}\n\n{extract}"


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    raw: str = args["url_or_title"]
    mode: str = args.get("mode", "intro")
    language: str = args.get("language", "en")
    target: str = args.get("target", "return_value")
    memory_key: str | None = args.get("memory_key")
    timeout: int = args.get("timeout", DEFAULT_TIMEOUT)

    if target in ("session_memory", "project_memory") and not memory_key:
        return "Error: 'memory_key' is required when target is 'session_memory' or 'project_memory'."

    # Determine lang + title: try URL parse first, fall back to treating raw as a title.
    parsed = _parse_url(raw)
    if parsed:
        lang, title = parsed
    else:
        lang = language
        title = raw

    result = _fetch_article(lang, title, mode, timeout)

    if target == "return_value":
        return result

    if target == "session_memory":
        memory = ensure_session_memory(session_data)
        memory[memory_key] = result
        return f"Wikipedia article written to session memory key {memory_key!r}."

    if target == "project_memory":
        project = os.getcwd()
        pool = get_pool()
        with pool.get_connection() as conn:
            KVManager(conn, project).set_value(memory_key, result)
            conn.commit()
        return f"Wikipedia article written to project memory key {memory_key!r}."

    return result
