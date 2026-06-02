## Skill: Browsing the Web

### Workflow

**1. Search** — `brave_web_search` for URLs, titles, descriptions. Use `freshness` for recent info.

**2. Answer if ready** — If results are sufficient, respond without scraping.

**3. Scrape** — Always write to session memory to avoid flooding context:
- `scrape_web_page(url=..., target='session_memory', memory_key='page_raw')` — general pages (default format is `raw`)
- `wikipedia(url=..., target='session_memory', memory_key='page_raw', mode='full')` — Wikipedia

**4. Extract** — Choose based on what you need:

- **`dom_analyzer` (preferred for HTML)** — structured navigation with controlled context use. Recommended workflow:
  1. `preview` with a low `depth` and small `truncate_chars` to orient yourself
  2. `find_nodes` with a CSS selector to locate target elements
  3. `get_node` / `get_attribute` with tight `truncate_chars` for initial inspection — set `truncate_chars=0` only for the specific node you've confirmed you need
  - Especially useful for extracting image `src` attributes when cataloging or caching images from a page (`find_nodes(selector='img')` then `get_attribute(..., attribute='src')`)

- **`summarize_memory_item`** — focused LLM summary; best for prose answers from large pages.
- **`session_memory(action="search_by_regex")`** — find specific sections in non-HTML content.
- **`line_reader`** — page through raw content when structure isn't needed.

**5. Answer** — Collect research and respond.

### Tools

- `brave_web_search` — Brave Search API; condensed URL/title/description results. Requires a `brave` service token.
- `scrape_web_page` — Respectful scraping with robots.txt, user-agent, and rate-limit jitter. Default format is `raw`.
- `wikipedia` — Clean text via Wikimedia API (no key). `mode='intro'` for a quick summary, `mode='full'` for the full article.
- `dom_analyzer` — Analyzes raw HTML stored in session memory. Use `preview` → `find_nodes` → `get_node`/`get_attribute` with truncation control.
- `summarize_memory_item` — Out-of-band LLM summary of a session memory item focused on a query.

### Tips

- Scrape a few pages at a time; read their content before deciding whether to fetch more.
- Always start `dom_analyzer` with conservative truncation — expand only once you've located the exact node you need.
- For image cataloging: `find_nodes(selector='img', limit=0)` then retrieve each `src` via `get_attribute` using the returned paths or `:nth-child()` selectors.
