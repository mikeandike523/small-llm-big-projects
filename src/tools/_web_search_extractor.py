import json
from typing import Any, Callable


_CONDENSE_SYSTEM_PROMPT = """\
You are a web search result extractor.

Given a raw web search API response JSON and the original search query, produce a
selector schema that condenses each useful result into a clean object.

Extract data relevant to the user's query, and ignore possibly irrelevant sources.

Output a JSON object with a single "results" array. Each element is a selector object
with two kinds of field values:

1. PATH SELECTORS (preferred for URLs, dates, titles, descriptions, and any verbatim
data): wrap a dot-delimited path in ${ }. List positions use numeric indices.
   Example: "${web.results.0.url}"

2. RAW VALUES (for fields you infer or classify yourself, e.g. type tags):
write the value directly.
   Example: "web"

Field rules:
- "url" is REQUIRED on every result — always use a path selector: "${...}"
- "type" is REQUIRED on every result — always a raw value: "web", "news", "video",
  "discussion", "faq", "article", etc.
- "date" MUST be a path selector if a date field exists in the source — never invent dates
- Include "title" and "description" as path selectors when available
- Add any other qualifying metadata that is useful
- Cover all result types present (web, news, discussions, FAQ, etc.)
- Do NOT reference thumbnail, favicon, or image fields

Example output:
{
  "results": [
    {"url": "${web.results.0.url}", "title": "${web.results.0.title}", "description": "${web.results.0.description}", "date": "${web.results.0.age}", "type": "web"},
    {"url": "${news.results.0.url}", "title": "${news.results.0.title}", "date": "${news.results.0.age}", "type": "news"}
  ]
}

Output ONLY valid JSON. No explanation, no markdown fences."""


def _extract_path(obj: Any, path: str) -> Any:
    """Walk a dot-delimited path through a nested dict/list, returning None if unresolvable."""
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _apply_selector_schema(data: dict, selector_results: list) -> list[dict]:
    """
    Resolve a list of selector objects against data.

    Each field value is either:
      - A path selector "${dot.delimited.path}" — resolved against data (best effort).
      - A raw value — used as-is (the LLM filled it in directly, e.g. "type": "news").
    """
    out = []
    for selector in selector_results:
        if not isinstance(selector, dict):
            continue
        item: dict = {}
        for key, value in selector.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                path = value[2:-1]
                resolved = _extract_path(data, path)
                if resolved is None:
                    continue
                item[key] = resolved if isinstance(resolved, (str, int, float, bool)) else str(resolved)
            else:
                # Raw value — accept any JSON-serialisable scalar or container
                item[key] = value
        if item.get("url"):
            out.append(item)
    return out


def _validate_extraction(results: Any) -> bool:
    """
    Return True if results has the required shape: a list of dicts where every
    item has a non-empty string "url" and a non-empty string "type".
    """
    if not isinstance(results, list):
        return False
    for item in results:
        if not isinstance(item, dict):
            return False
        if not isinstance(item.get("url"), str) or not item["url"]:
            return False
        if not isinstance(item.get("type"), str) or not item["type"]:
            return False
    return True


def _condense_with_llm(
    filtered_data: dict,
    query: str,
    max_tries: int = 1,
    on_chunk: Callable[[str], None] | None = None,
) -> list[dict] | None:
    """
    Ask the configured LLM to produce a selector schema for the search results,
    then extract and validate values via path walking.

    Retries up to max_tries times on shape mismatches or parse failures.
    Returns None when all attempts fail, so callers can fall back to raw filtered JSON.
    """
    from src.utils.llm.factory import make_llm

    llm = make_llm()
    if llm is None:
        return None

    messages = [
        {"role": "system", "content": _CONDENSE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Search Query: {query}\n\n"
                f"Json Data:\n{json.dumps(filtered_data, ensure_ascii=False)}"
            ),
        },
    ]

    total = max(1, max_tries)
    for attempt in range(1, total + 1):
        if on_chunk:
            on_chunk(f"\nAttempting extraction try {attempt}/{total}...")
        try:
            fetch_result = llm.fetch(messages)
            content = (fetch_result.content or "").strip()
            if not content:
                continue
            # Strip accidental markdown fences
            if content.startswith("```"):
                lines = content.splitlines()
                start = 1
                end = len(lines) - 1 if lines[-1].strip() in ("```", "~~~") else len(lines)
                content = "\n".join(lines[start:end])
            schema = json.loads(content)
            if on_chunk:
                on_chunk(f"\nSelector:\n{json.dumps(schema, ensure_ascii=False, indent=2)}")
            selector_results = schema.get("results")
            if not isinstance(selector_results, list):
                continue
            extracted = _apply_selector_schema(filtered_data, selector_results)
            if _validate_extraction(extracted):
                return extracted
        except Exception:
            continue

    return None
