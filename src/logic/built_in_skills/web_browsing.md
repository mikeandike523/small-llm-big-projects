## Skill: Browsing the Web

Use `brave_web_search` to find relevant URLs, then fetch content with one of:

- `scrape_web_page` — respectful HTML scraping with proper user-agent, robots.txt checking, and rate-limit jitter. Best for general web pages.
- `wikipedia` — clean plain-text extraction via the Wikimedia API (no key needed). Prefer this over `scrape_web_page` whenever a URL is on wikipedia.org. Pass the URL directly; language and title are extracted automatically. Use `mode='intro'` for a quick summary, `mode='full'` for the complete article.
- `basic_web_request` — raw HTTP requests for APIs or pages that need custom headers, auth tokens, or specific methods.

**Always route large responses to session memory** — use `target='session_memory'` on any of the above tools. Never return large web content inline; it wastes context.

Once content is in session memory:
- `session_memory_text_editor(action="count_lines")` to check size before reading
- `session_memory_text_editor(action="read_lines", number_lines=true)` to page through in chunks
- `session_memory(action="search_by_regex")` to find relevant sections without reading everything
- `session_memory(action="set")` to save important snippets under a named key for later recall
