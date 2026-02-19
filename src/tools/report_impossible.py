import json

DEFINITION = {
    "type": "function",
    "function": {
        "name": "report_impossible",
        "description": (
            "Call this when you have genuinely determined that the current todo list "
            "cannot be completed with the tools and knowledge available to you. "
            "Provide a clear explanation. This immediately stops the agentic loop "
            "and informs the user. Do not use this as a shortcut — only call it when "
            "truly stuck."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Clear explanation of why the task cannot be completed.",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
}


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    reason = args.get("reason", "No reason provided.")
    session_data["_report_impossible"] = reason
    return json.dumps({"acknowledged": True, "reason": reason})
