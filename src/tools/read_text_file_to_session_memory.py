from src.utils.git_heuristic_is_binary import git_heuristic_is_binary

import os


LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "read_text_file_to_session_memory",
        "description": (
            "Read an entire text file into session memory. "
            "Encoding must be UTF-8. "
            "Line endings are preserved verbatim -- absolutely no automatic EOL conversion "
            "is performed. CRLF files stay CRLF, LF files stay LF, exactly as on disk."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description":
                    "The path of the file. It can be either relative to cwd, or absolute."
                },
                "memory_key": {
                    "type": "string",
                    "description": (
                        "The memory key to write the file contents to. "
                        "Required when target is 'session_memory' or 'project_memory'."
                    ),
                },
            },
            "required": ["filepath","memory_key"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    from src.tools._approval import needs_path_approval
    return needs_path_approval(args.get("filepath"))


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args, session_data):
    filepath = args["filepath"]

    rp = os.path.realpath(filepath)

    if os.path.isfile(rp):
        if git_heuristic_is_binary(rp):
            raise ValueError(f"""
File at requested path is binary.
Not suitable for session memory editing tools.
Consider skipping, especially for code reviews.
Consider skipping if ignored by git, compare against the result of
`list_working_tree` tool                       
                            `
                             
                             """.strip())

    with open(filepath, "r", encoding="utf-8", newline='') as fl: # Preserve CRLF from disk
        contents = fl.read()

    memory_key = args["memory_key"]

    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)
    memory[memory_key] = contents
    return f"Contents of file {filepath} were written to session memory item {memory_key}"
