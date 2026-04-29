DEFAULT_TIMEOUT = None
TIMEOUT_HINT = None

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "ask_human",
        "description": (
            "Pause the task and ask the user a question. Use when you genuinely need "
            "clarification, a decision, or information you cannot determine yourself. "
            "The task resumes once the user answers. Do not use this to confirm steps "
            "you are already confident about."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user.",
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def execute(args: dict, _session_data={}, special_resources={}) -> str:
    question = args.get("question", "").strip()
    if not question:
        return "Error: 'question' parameter is required."
    ask_fn = special_resources.get("ask_human_fn")
    if not ask_fn:
        return "Error: ask_human is not available in this context."
    answer = ask_fn(question)
    if answer is None:
        return "The user did not respond (turn was cancelled or timed out)."
    return answer
