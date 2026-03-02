from __future__ import annotations

from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool


def _network_available() -> bool:
    """Quick reachability check for en.wikipedia.org."""
    import httpx
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get("https://en.wikipedia.org/w/api.php?action=query&format=json&titles=Main_Page")
            return resp.status_code == 200
    except Exception:
        return False


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("wikipedia")
    try:
        # --- Validation (no network needed) ---

        # memory_key required when target=session_memory
        r = execute_tool("wikipedia", {
            "url_or_title": "Python (programming language)",
            "target": "session_memory",
        }, env.session_data)
        cl.check(
            "memory_key required",
            "Returns error when target=session_memory but memory_key is absent",
            r.startswith("Error:") and "memory_key" in r,
            f"got: {r!r}",
        )

        # --- URL parsing (no network needed — tests internal helper) ---
        from src.tools.wikipedia import _parse_url

        parsed = _parse_url("https://en.wikipedia.org/wiki/Python_(programming_language)")
        cl.check(
            "url parse: standard desktop",
            "Parses lang and title from a standard desktop Wikipedia URL",
            parsed == ("en", "Python_(programming_language)"),
            f"got: {parsed!r}",
        )

        parsed_m = _parse_url("https://en.m.wikipedia.org/wiki/Python_(programming_language)")
        cl.check(
            "url parse: mobile",
            "Parses lang and title from a mobile (m.) Wikipedia URL",
            parsed_m is not None and parsed_m[0] == "en" and parsed_m[1] == "Python_(programming_language)",
            f"got: {parsed_m!r}",
        )

        parsed_de = _parse_url("https://de.wikipedia.org/wiki/Python_(Programmiersprache)")
        cl.check(
            "url parse: non-english",
            "Parses lang='de' from a German Wikipedia URL",
            parsed_de is not None and parsed_de[0] == "de",
            f"got: {parsed_de!r}",
        )

        not_wiki = _parse_url("https://example.com/wiki/Foo")
        cl.check(
            "url parse: non-wikipedia returns None",
            "Returns None for a URL that is not on wikipedia.org",
            not_wiki is None,
            f"got: {not_wiki!r}",
        )

        bare_title = _parse_url("Python programming language")
        cl.check(
            "url parse: bare title returns None",
            "Returns None for a plain title (not a URL), triggering fallback",
            bare_title is None,
            f"got: {bare_title!r}",
        )

        # --- Live network tests ---
        if not _network_available():
            cl.skip("Wikipedia not reachable — live fetch tests skipped")
            return cl.result()

        # intro mode via URL
        r = execute_tool("wikipedia", {
            "url_or_title": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "mode": "intro",
        }, env.session_data)
        cl.check(
            "intro via url: no error",
            "Fetching intro via Wikipedia URL returns non-error string",
            isinstance(r, str) and not r.startswith("Error:"),
            f"got first 200 chars: {r[:200]!r}",
        )
        cl.check(
            "intro via url: header present",
            "Result contains 'Wikipedia:' header line",
            "Wikipedia:" in r,
            f"got first 200 chars: {r[:200]!r}",
        )
        cl.check(
            "intro via url: mentions python",
            "Result text mentions Python (the language)",
            "Python" in r,
            f"got first 200 chars: {r[:200]!r}",
        )

        # intro mode via bare title
        r2 = execute_tool("wikipedia", {
            "url_or_title": "Python (programming language)",
            "mode": "intro",
            "language": "en",
        }, env.session_data)
        cl.check(
            "intro via title: no error",
            "Fetching intro via bare title returns non-error string",
            isinstance(r2, str) and not r2.startswith("Error:"),
            f"got first 200 chars: {r2[:200]!r}",
        )

        # target=session_memory
        r3 = execute_tool("wikipedia", {
            "url_or_title": "Python (programming language)",
            "mode": "intro",
            "target": "session_memory",
            "memory_key": "wiki_test",
        }, env.session_data)
        stored = env.session_data.get("memory", {}).get("wiki_test")
        cl.check(
            "target session_memory: confirmation",
            "Returns confirmation message mentioning the memory key",
            "wiki_test" in r3,
            f"got: {r3!r}",
        )
        cl.check(
            "target session_memory: stored value non-empty",
            "Value written to session memory is non-empty",
            isinstance(stored, str) and len(stored) > 0,
            f"stored type: {type(stored).__name__}",
        )

        # Missing article
        r4 = execute_tool("wikipedia", {
            "url_or_title": "Xyzzy_NoSuchArticle_slbp_test_12345",
        }, env.session_data)
        cl.check(
            "missing article",
            "Returns error for a non-existent article title",
            r4.startswith("Error:"),
            f"got: {r4!r}",
        )

    except Exception as e:
        cl.record_exception(e)
    return cl.result()
