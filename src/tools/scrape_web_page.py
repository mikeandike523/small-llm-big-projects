from __future__ import annotations

import random
import re
import time
from typing import Literal
from urllib.parse import urlparse

import httpx

from src.utils.http.helpers import ensure_session_memory
from src.tools._validate_timeout import validate_timeout
from src.tools._cancellation import check_cancelled, get_cancel_event, wait_or_cancel
from src.tools._async_http import request_with_cancel
from src.utils.exceptions import ToolTimeoutError

DEFAULT_TIMEOUT = 20  # seconds per request
MIN_TIMEOUT = 5
MAX_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3  # transient-failure retries
DEFAULT_MIN_DELAY = 1.0  # politeness delay before fetching
_JITTER = (0.05, 0.35)  # random seconds added on top of min_delay
_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRY_DELAY = 30.0

_USER_AGENT = "Mozilla/5.0 (compatible; slbp-agent/1.0; +https://github.com/mikeandike523/small-llm-big-projects)"
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Module-level caches (live for the process lifetime — appropriate for a server tool).
_robots_cache: dict[str, tuple] = {}  # origin -> (Protego | None, timestamp)
_last_request_time: dict[str, float] = {}
_ROBOTS_TTL = 3600  # re-fetch robots.txt after 1 hour


DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "scrape_web_page",
        "description": (
            "Respectfully scrape a web page with proper user agent, robots.txt checking, and jitter. "
            "Pairs well with brave_web_search. "
            "Robots.txt failures are fail-open (request proceeds). "
            "For large pages use target='session_memory' and read in chunks with text_editor."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to scrape.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Per-request timeout in seconds "
                        f"(minimum {MIN_TIMEOUT}, maximum {MAX_TIMEOUT}, default {DEFAULT_TIMEOUT}). "
                        "Applies to both the robots.txt prefetch and the main fetch."
                    ),
                    "minimum": MIN_TIMEOUT,
                    "maximum": MAX_TIMEOUT,
                },
                "max_retries": {
                    "type": "integer",
                    "description": (
                        f"Maximum retry attempts on transient failures "
                        f"(5xx, 429, connection errors; default {DEFAULT_MAX_RETRIES})."
                    ),
                    "minimum": 0,
                    "maximum": 5,
                },
                "min_delay_seconds": {
                    "type": "number",
                    "description": (
                        f"Minimum politeness delay in seconds before fetching (default {DEFAULT_MIN_DELAY}). "
                        "A small random jitter is added on top. Set to 0 to skip delay."
                    ),
                    "minimum": 0.0,
                    "maximum": 10.0,
                },
                "check_robots": {
                    "type": "boolean",
                    "description": (
                        "Whether to check robots.txt before fetching (default true). "
                        "If robots.txt cannot be fetched or parsed, the request proceeds anyway (fail-open). "
                        "Set to false to skip the check entirely."
                    ),
                },
                "accept": {
                    "type": "string",
                    "description": (
                        "Value for the Accept header (default '*/*'). "
                        "Use to request a specific content type, e.g. 'text/html' or 'application/json'."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Value for the Accept-Language header. "
                        "Omit to send no language preference (server decides). "
                        "Examples: 'fr', 'ja', 'en-US,en;q=0.9'."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["xml", "markdown", "text", "raw"],
                    "description": (
                        "Readable output format. "
                        "'raw' (default) returns the original response body -- use this when you plan to analyze the HTML with dom_analyzer. "
                        "'xml' extracts structured content as trafilatura XML -- reliable and well-delimited. "
                        "'markdown' extracts and formats the main page content as Markdown. "
                        "'text' extracts plain text."
                    ),
                },
                "target": {
                    "type": "string",
                    "enum": ["return_value", "session_memory"],
                    "description": (
                        "Where to send the page content. "
                        "'return_value' (default) returns it directly. "
                        "'session_memory' writes to a session memory key."
                    ),
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write results to. "
                        "Required when target is 'session_memory'."
                    ),
                },
                "apply_basic_filters": {
                    "type": "boolean",
                    "description": (
                        "When true (default), apply basic noise-reduction filters to the output. "
                        "Currently strips base64-encoded data URIs (e.g. inline images) and replaces "
                        "them with a '<base64 data>' placeholder. Applies in all output modes."
                    ),
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(
    args: dict, session_data: dict | None = None, special_resources: dict | None = None
) -> bool:
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _origin(url: str) -> str | None:
    try:
        u = urlparse(url)
        if not u.scheme or not u.netloc:
            return None
        return f"{u.scheme}://{u.netloc}"
    except Exception:
        return None


def _host(url: str) -> str | None:
    try:
        return urlparse(url).netloc or None
    except Exception:
        return None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After", "").strip()
        try:
            return min(max(float(retry_after), 0.0), _MAX_RETRY_DELAY)
        except ValueError:
            pass
    return min(float(2**attempt), _MAX_RETRY_DELAY)


def _request_with_retries(
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
    max_retries: int,
    cancel_event=None,
) -> httpx.Response:
    """GET with bounded, cancellation-aware transient retries."""
    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            response = request_with_cancel(
                "scrape_web_page",
                "GET",
                url,
                cancel_event=cancel_event,
                client_kwargs={"timeout": timeout, "follow_redirects": True},
                headers=headers,
            )
        except ToolTimeoutError:
            raise
        except httpx.RequestError:
            if attempt >= max_retries:
                raise
        else:
            if response.status_code not in _RETRY_STATUS_CODES:
                return response
            if attempt >= max_retries:
                return response

        wait_or_cancel(
            "scrape_web_page",
            cancel_event,
            _retry_delay(response, attempt),
        )

    raise RuntimeError("unreachable retry loop")


def _polite_delay(host: str, min_delay: float, cancel_event=None) -> None:
    """Sleep if needed to honour per-host politeness, then add jitter."""
    now = time.monotonic()
    last = _last_request_time.get(host, 0.0)
    wait = min_delay - (now - last)
    jitter = random.uniform(*_JITTER)
    sleep_for = max(0.0, wait) + jitter
    if sleep_for > 0:
        wait_or_cancel("scrape_web_page", cancel_event, sleep_for)
    _last_request_time[host] = time.monotonic()


def _check_robots(
    url: str,
    headers: dict[str, str],
    timeout: int,
    max_retries: int,
    cancel_event=None,
) -> tuple[bool, str | None]:
    """
    Return (allowed, note).

    - allowed=True if fetching is permitted or the check is inconclusive (fail-open).
    - allowed=False only when robots.txt explicitly disallows the URL.
    - note is a human-readable explanation when allowed=False or on soft errors.
    """
    try:
        from protego import Protego
    except ImportError:
        return True, "protego not installed; robots.txt check skipped"

    origin = _origin(url)
    if not origin:
        return True, None

    now = time.monotonic()
    cached = _robots_cache.get(origin)
    if cached and (now - cached[1]) < _ROBOTS_TTL:
        rp = cached[0]
    else:
        robots_url = f"{origin}/robots.txt"
        rp = None
        try:
            check_cancelled("scrape_web_page", cancel_event)
            r = _request_with_retries(
                robots_url,
                headers=headers,
                timeout=timeout,
                max_retries=max_retries,
                cancel_event=cancel_event,
            )
            check_cancelled("scrape_web_page", cancel_event)
            if r.status_code == 200:
                try:
                    rp = Protego.parse(r.text)
                except Exception:
                    # Parse failure -> fail-open (rp stays None)
                    pass
            elif r.status_code == 404:
                rp = Protego.parse("")  # no robots.txt -> allow all
            # Any other status -> fail-open (rp stays None)
        except ToolTimeoutError:
            raise
        except Exception:
            pass  # Network failure -> fail-open
        _robots_cache[origin] = (rp, now)

    if rp is None:
        # Inconclusive (fetch/parse failed) -> fail-open
        return True, "robots.txt could not be fetched or parsed; proceeding anyway"

    try:
        allowed = bool(rp.can_fetch(_USER_AGENT, url))
    except Exception:
        return True, "robots.txt can_fetch check errored; proceeding anyway"

    if not allowed:
        return False, f"Blocked by robots.txt at {origin}"
    return True, None


_DATA_URI_RE = re.compile(r"data:[a-zA-Z]+/[a-zA-Z0-9.+\-]+;base64,[A-Za-z0-9+/=]+")


def _apply_basic_filters(text: str) -> str:
    return _DATA_URI_RE.sub("<base64 data>", text)


def _render_content(
    body_text: str, fmt: Literal["xml", "markdown", "text", "raw"]
) -> str:
    if fmt == "raw":
        return body_text

    try:
        import trafilatura
    except ImportError:
        return body_text

    if fmt == "xml":
        output_format = "xml"
    elif fmt == "markdown":
        output_format = "markdown"
    else:
        output_format = "txt"

    try:
        extracted = trafilatura.extract(
            body_text,
            output_format=output_format,
            include_links=True,
            include_formatting=fmt != "xml",
            favor_precision=True,
        )
    except Exception:
        extracted = None

    if extracted:
        return extracted.strip()
    return body_text


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


def execute(
    args: dict,
    session_data: dict | None = None,
    special_resources: dict | None = None,
) -> str:
    cancel_event = get_cancel_event(special_resources)
    check_cancelled("scrape_web_page", cancel_event)
    if session_data is None:
        session_data = {}

    url: str = args["url"]
    timeout: int = args.get("timeout", DEFAULT_TIMEOUT)
    validate_timeout(
        "scrape_web_page",
        timeout,
        DEFAULT_TIMEOUT,
        MAX_TIMEOUT,
        min_timeout=MIN_TIMEOUT,
    )
    max_retries: int = args.get("max_retries", DEFAULT_MAX_RETRIES)
    min_delay: float = args.get("min_delay_seconds", DEFAULT_MIN_DELAY)
    check_robots_flag: bool = args.get("check_robots", True)
    accept: str | None = args.get("accept")
    language: str | None = args.get("language")
    output_format: Literal["xml", "markdown", "text", "raw"] = args.get("format", "raw")
    target: str = args.get("target", "return_value")
    memory_key: str | None = args.get("memory_key")
    apply_filters: bool = args.get("apply_basic_filters", True)

    if target == "session_memory" and not memory_key:
        return "Error: 'memory_key' is required when target is 'session_memory'."

    host = _host(url)
    if not host:
        return f"Error: Invalid URL {url!r}."

    headers = dict(_HEADERS)

    # --- apply optional per-call header overrides ---
    if accept:
        headers["Accept"] = accept
    if language:
        headers["Accept-Language"] = language

    # --- robots.txt check (fail-open) ---
    if check_robots_flag:
        allowed, note = _check_robots(
            url, headers, timeout, max_retries, cancel_event
        )
        if not allowed:
            return f"Error: {note}"
        # note (soft warnings) are silently dropped — don't clutter the result

    # --- politeness delay ---
    try:
        _polite_delay(host, min_delay, cancel_event)
    except ToolTimeoutError:
        raise
    except Exception:
        pass  # delay failure is never fatal

    # --- fetch ---
    try:
        check_cancelled("scrape_web_page", cancel_event)
        resp = _request_with_retries(
            url,
            headers=headers,
            timeout=timeout,
            max_retries=max_retries,
            cancel_event=cancel_event,
        )
        check_cancelled("scrape_web_page", cancel_event)
    except httpx.TimeoutException:
        return f"Error: Request timed out after {timeout}s fetching {url!r}."
    except httpx.TooManyRedirects:
        return f"Error: Too many redirects fetching {url!r}."
    except httpx.RequestError as e:
        return f"Error: Request failed: {type(e).__name__}: {e}"
    except ToolTimeoutError:
        raise
    except Exception as e:
        return f"Error: Unexpected error fetching {url!r}: {type(e).__name__}: {e}"

    # --- handle rate-limit / overload after bounded retries are exhausted ---
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        return (
            f"Error: Server returned 429 Too Many Requests for {url!r}. "
            f"Retry-After: {retry_after}"
        )

    # --- build result ---
    content_type = resp.headers.get("content-type", "")
    header_line = f"HTTP {resp.status_code} | {content_type}"
    body_text = resp.content.decode("utf-8", errors="replace")
    check_cancelled("scrape_web_page", cancel_event)
    rendered = _render_content(body_text, output_format)
    check_cancelled("scrape_web_page", cancel_event)
    result = f"{header_line}\n\n{rendered}"
    if apply_filters:
        result = _apply_basic_filters(result)

    # --- deliver ---
    if target == "return_value":
        return result

    if target == "session_memory":
        memory = ensure_session_memory(session_data)
        memory[memory_key] = result
        return f"Page content written to session memory key {memory_key!r}."

    return result
