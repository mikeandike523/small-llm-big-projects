## Skill: Browsing the Web

### Workflow

**1. Search** — Use `brave_web_search` to get results with URLs, titles, and descriptions. Use `freshness` for up-to-date info.

**2. Answer if ready** — If the facts are sufficient to answer the question, respond directly without scraping.

**3. Scrape for more info** — Fetch a URL from the results:
- `scrape_web_page(url=..., target='session_memory', memory_key='page_raw')` — general web pages
- `wikipedia(url=..., target='session_memory', memory_key='page_raw', mode='full')` — Wikipedia (prefer over `scrape_web_page` for wikipedia.org URLs)

Always use `target='session_memory'` — never return large web content inline; it wastes context.

**4. Extract what you need** from the scraped content:
- `summarize_memory_item(memory_key='page_raw', query='...', output_key='page_summary')` — focused LLM summary; best for concise answers.
- `text_editor(action="search_by_regex", key='page_raw', ...)` — find specific sections without reading everything.
- `line_reader(action="count_lines"/"read_lines", session_memory_key='page_raw')` — page through raw content; best for structured content.

**5. Answer** — Collect your research and respond.

### Tools

- `brave_web_search` — Brave Search API. Returns condensed results with URLs, titles, descriptions. Requires a `brave` service token.
- `scrape_web_page` — Respectful HTML scraping with user-agent, robots.txt checking, and rate-limit jitter.
- `wikipedia` — Clean plain-text extraction via the Wikimedia API (no key needed). Use `mode='intro'` for a quick summary, `mode='full'` for the complete article.
- `summarize_memory_item` — Out-of-band LLM call to summarize a session memory item with respect to a query. Pass `output_key` to write the summary to a new key instead of returning inline.

### Tips

- Scrape only a few pages at a time — read their content before deciding whether to fetch more.
- You may not need every URL to get a clear picture — focus on relevance.
- If you notice relevant URLs in scraped pages, follow them by scraping and summarizing the same way.
