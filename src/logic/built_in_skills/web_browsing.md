## Skill: Browsing the Web

### General Workflow

Web research follows a three-step pattern:

**1. Search** — Use `brave_web_search` to get a list of results (URLs, titles, descriptions).
Pick the most promising URLs based on the result metadata.

**2. Scrape** — Fetch the selected page into session memory:
- `scrape_web_page(url=..., target='session_memory', memory_key='page_raw')` — general web pages
- `wikipedia(url=..., target='session_memory', memory_key='page_raw', mode='full')` — Wikipedia pages (prefer this over `scrape_web_page` for wikipedia.org URLs)

Always use `target='session_memory'` — never return large web content inline; it wastes context.

**3. Read or Summarize** — Extract what you need from the scraped content:
- `summarize_memory_item(memory_key='page_raw', query='...', output_key='page_summary')` — ask the LLM to summarize the content focused on your query. Best when you want a concise answer.
- `text_editor(action="search_by_regex", key='page_raw', ...)` — find relevant sections without reading everything. Best when you need a specific passage or value.
- `line_reader(action="count_lines", session_memory_key='page_raw')` then `line_reader(action="read_lines", ...)` — page through the raw content in chunks. Best for thorough reads of structured content.

### Tools

- `brave_web_search` — Brave Search API. Returns a condensed list of results with URLs, titles, and descriptions. Requires a `brave` service token.
- `scrape_web_page` — Respectful HTML scraping with proper user-agent, robots.txt checking, and rate-limit jitter.
- `wikipedia` — Clean plain-text extraction via the Wikimedia API (no key needed). Use `mode='intro'` for a quick summary, `mode='full'` for the complete article.
- `summarize_memory_item` — Out-of-band LLM call to summarize a session memory item with respect to a query. Pass `output_key` to write the summary to a new session memory key instead of returning inline.

### Working with Session Memory

Once content is in session memory:
- `summarize_memory_item(memory_key=..., query=...)` to get a focused summary via LLM
- `text_editor(action="search_by_regex", key=...)` to find relevant sections without reading everything
- `line_reader(action="count_lines", session_memory_key=...)` to check size before reading
- `line_reader(action="read_lines", session_memory_key=..., number_lines=true)` to page through in chunks
- `session_memory(action="search_by_regex", key=...)` to search for patterns directly in the stored value
- `session_memory(action="set")` to save important snippets under a named key for later recall

### Return Stubs

If a tool result begins with `** STUBBED LONG RETURN VALUE **`, the full content is already stored
in session memory at the key shown in the stub header. Treat it exactly like any other session memory value:
- `summarize_memory_item(memory_key=<stub-key>, query=...)` to summarize without reading everything
- `session_memory(action="search_by_regex", key=<stub-key>, ...)` to search the content
- `line_reader(action="count_lines", session_memory_key=<stub-key>)` for line count
- `line_reader(action="read_lines", session_memory_key=<stub-key>, start_line=..., end_line=...)` to read in chunks

### Tips

- Scrape only a few pages at a time — read their content before deciding whether to fetch more.
- Prefer `summarize_memory_item` over reading in chunks when you need a quick focused answer.
- Prefer `search_by_regex` over summarization when you need a specific value or passage verbatim.
