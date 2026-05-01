DEFINITION = {
    "type": "function",
    "function": {
        "name": "report_impossible",
        "description": (
            "Report that the current task cannot be completed as requested. "
            "Use ONLY when todo items remain open and all feasible approaches have been exhausted "
            "(e.g. a required tool was denied and no alternative exists, a tool keeps failing, "
            "or the task is fundamentally outside your capabilities). "
            "Do not use this to avoid difficult steps — try alternatives first. "
            "The reason you provide becomes the final response for this turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Clear explanation of why the task cannot be completed and what was attempted.",
                },
            },
            "required": ["reason"],
        },
    },
}


def execute(args: dict, session_data: dict) -> str:
    return args.get("reason", "Task reported as impossible.")
