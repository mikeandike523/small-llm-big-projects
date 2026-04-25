## Skill: Browsing the Web

`brave_web_search` now automatically scrapes each result URL and attaches a `"facts"` list to every result object it can successfully fetch and summarise. Read those facts first — they are often sufficient.

If a result is **missing a `"facts"` field**, the automatic scrape failed or the page was too large to summarise. In that case, fetch it yourself:

- `scrape_web_page` — respectful HTML scraping with proper user-agent, robots.txt checking, and rate-limit jitter. Best for general web pages.
- `wikipedia` — clean plain-text extraction via the Wikimedia API (no key needed). Prefer this over `scrape_web_page` whenever a URL is on wikipedia.org. Pass the URL directly; language and title are extracted automatically. Use `mode='intro'` for a quick summary, `mode='full'` for the complete article.

**Always route large responses to session memory** — use `target='session_memory'` on any of the above tools. Never return large web content inline; it wastes context.

Once content is in session memory:
- `text_editor(action="count_lines", key=...)` to check size before reading
- `text_editor(action="read_lines", key=..., number_lines=true)` to page through in chunks
- `text_editor(action="search_by_regex", key=...)` to find relevant sections without reading everything
- `session_memory(action="search_by_regex", key=...)` to search for patterns directly in the stored value
- `session_memory(action="set")` to save important snippets under a named key for later recall

**Return stubs are session memory.** If a tool result came back as a stub (`** STUBBED LONG RETURN VALUE **`),
the full content is already stored in session memory at the key named in the stub header. You can use it
exactly like any other session memory value:
- `session_memory(action="search_by_regex", key=<stub-key>, ...)` to search without reading everything
- `return_stub_line_reader(action="count_lines", session_memory_key=<stub-key>)` to get the line count
- `return_stub_line_reader(action="read_lines", session_memory_key=<stub-key>, start_line=..., end_line=...)` to read in chunks

READ YOUR SCRAPES EARLY

Don't scrape hundreds of pages, scrape a few, and then start reading their contents with the tools above.