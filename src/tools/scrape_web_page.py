from __future__ import annotations

import random

import time
from typing import Literal
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.http.helpers import ensure_session_memory
from src.utils.text_truncation import truncate_long_lines as _truncate_long_lines

DEFAULT_TIMEOUT = 20  # seconds per request
DEFAULT_MAX_RETRIES = 3  # transient-failure retries
DEFAULT_MIN_DELAY = 1.0  # politeness delay before fetching
_JITTER = (0.05, 0.35)  # random seconds added on top of min_delay

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
                        f"Per-request timeout in seconds (default {DEFAULT_TIMEOUT}). "
                        "Applies to both the robots.txt prefetch and the main fetch."
                    ),
                    "minimum": 5,
                    "maximum": 60,
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
                        "'xml' (default) extracts structured content as trafilatura XML -- reliable and well-delimited. "
                        "'markdown' extracts and formats the main page content as Markdown. "
                        "'text' extracts plain text. "
                        "'raw' returns the original response body without readability post-processing."
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
                "max_line_length": {
                    "type": "integer",
                    "description": (
                        "Truncate lines in the returned content longer than this many characters, "
                        "appending '[... N more bytes]'. "
                        "Protects against minified HTML/CSS/JS with very long lines. "
                        "0 disables the limit. Range: 0-256. Default: 160."
                    ),
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
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


def _make_session(max_retries: int) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(_HEADERS)
    return session


def _polite_delay(host: str, min_delay: float) -> None:
    """Sleep if needed to honour per-host politeness, then add jitter."""
    now = time.monotonic()
    last = _last_request_time.get(host, 0.0)
    wait = min_delay - (now - last)
    jitter = random.uniform(*_JITTER)
    sleep_for = max(0.0, wait) + jitter
    if sleep_for > 0:
        time.sleep(sleep_for)
    _last_request_time[host] = time.monotonic()


def _check_robots(
    url: str, session: requests.Session, timeout: int
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
            r = session.get(robots_url, timeout=timeout)
            if r.status_code == 200:
                try:
                    rp = Protego.parse(r.text)
                except Exception:
                    # Parse failure -> fail-open (rp stays None)
                    pass
            elif r.status_code == 404:
                rp = Protego.parse("")  # no robots.txt -> allow all
            # Any other status -> fail-open (rp stays None)
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


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    url: str = args["url"]
    timeout: int = args.get("timeout", DEFAULT_TIMEOUT)
    max_retries: int = args.get("max_retries", DEFAULT_MAX_RETRIES)
    min_delay: float = args.get("min_delay_seconds", DEFAULT_MIN_DELAY)
    check_robots_flag: bool = args.get("check_robots", True)
    accept: str | None = args.get("accept")
    language: str | None = args.get("language")
    output_format: Literal["xml", "markdown", "text", "raw"] = args.get("format", "xml")
    target: str = args.get("target", "return_value")
    memory_key: str | None = args.get("memory_key")
    max_line_length: int = max(0, min(256, args.get("max_line_length", 160)))

    if target == "session_memory" and not memory_key:
        return "Error: 'memory_key' is required when target is 'session_memory'."

    host = _host(url)
    if not host:
        return f"Error: Invalid URL {url!r}."

    session = _make_session(max_retries)

    # --- apply optional per-call header overrides ---
    if accept:
        session.headers["Accept"] = accept
    if language:
        session.headers["Accept-Language"] = language

    # --- robots.txt check (fail-open) ---
    if check_robots_flag:
        allowed, note = _check_robots(url, session, timeout)
        if not allowed:
            return f"Error: {note}"
        # note (soft warnings) are silently dropped — don't clutter the result

    # --- politeness delay ---
    try:
        _polite_delay(host, min_delay)
    except Exception:
        pass  # delay failure is never fatal

    # --- fetch ---
    try:
        resp = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.exceptions.Timeout:
        return f"Error: Request timed out after {timeout}s fetching {url!r}."
    except requests.exceptions.TooManyRedirects:
        return f"Error: Too many redirects fetching {url!r}."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Error: Unexpected error fetching {url!r}: {type(e).__name__}: {e}"

    # --- handle rate-limit / overload (not retried by urllib3 on non-GET?) ---
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
    rendered = _render_content(body_text, output_format)
    result = _truncate_long_lines(f"{header_line}\n\n{rendered}", max_line_length)

    # --- deliver ---
    if target == "return_value":
        return result

    if target == "session_memory":
        memory = ensure_session_memory(session_data)
        memory[memory_key] = result
        return f"Page content written to session memory key {memory_key!r}."

    return result
