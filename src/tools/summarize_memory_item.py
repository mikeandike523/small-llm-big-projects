from __future__ import annotations

from src.tools._memory import ensure_session_memory

NO_STUB = True

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "summarize_memory_item",
        "description": (
            "Summarize a session memory item with respect to a query using an out-of-band LLM call. "
            "Use this after scraping a web page into session memory to extract relevant information "
            "without reading the full content. The summary is focused on the provided query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_key": {
                    "type": "string",
                    "description": "The session memory key whose value will be summarized.",
                },
                "query": {
                    "type": "string",
                    "description": "The query or topic to focus the summary on.",
                },
                "output_key": {
                    "type": "string",
                    "description": (
                        "Optional session memory key to write the summary to. "
                        "If omitted, the summary is returned directly."
                    ),
                },
            },
            "required": ["memory_key", "query"],
            "additionalProperties": False,
        },
    },
}

_SUMMARIZE_SYSTEM_PROMPT = """\
You are a research assistant. Given the content of a document and a research query,
write a concise, focused summary of the information most relevant to that query.

Be direct and factual. Omit unrelated content. Preserve important details, names,
dates, and numbers. Write in plain prose — no markdown headers or bullet points unless
the original content is inherently list-like.

Do NOT include meta-commentary like "The page discusses..." or "According to the source...".
Just provide the summary directly."""


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    memory_key: str = args["memory_key"]
    query: str = args["query"]
    output_key: str | None = args.get("output_key")

    on_chunk = (special_resources or {}).get("on_chunk")

    memory = ensure_session_memory(session_data)
    content = memory.get(memory_key)

    if content is None:
        return f"Error: No session memory item found at key '{memory_key}'."

    if not isinstance(content, str):
        content = str(content)

    if not content.strip():
        return f"Error: Session memory item '{memory_key}' is empty."

    from src.utils.llm.factory import make_llm

    llm = make_llm()
    if llm is None:
        return "Error: No LLM configured. Cannot summarize."

    if on_chunk:
        on_chunk(f"Summarizing '{memory_key}' with LLM...")

    messages = [
        {"role": "system", "content": _SUMMARIZE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Query: {query}\n\nDocument Content:\n{content}",
        },
    ]

    try:
        fetch_result = llm.fetch(messages)
        summary = (fetch_result.content or "").strip()
    except Exception as e:
        return f"Error: LLM summarization failed: {type(e).__name__}: {e}"

    if not summary:
        return "Error: LLM returned an empty summary."

    if output_key:
        memory[output_key] = summary
        return f"Summary written to session memory key '{output_key}'."

    return summary
