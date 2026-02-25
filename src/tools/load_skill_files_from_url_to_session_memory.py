from __future__ import annotations

import json

import httpx

from src.utils.http.helpers import ensure_session_memory

LEAVE_OUT = "PARAMS_ONLY"

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "load_skill_files_from_url_to_session_memory",
        "description": (
            "Fetch a skill.json from a URL and load all its declared files into session memory. "
            "The skill.json must have a 'version' string field and a 'files' object mapping "
            "file names to fetch URLs. Each file is stored as skill-files.<skill_name>.<file_name>. "
            "The skill.json itself is stored as skill-files.<skill_name>.skill.json. "
            "Loading is idempotent: if the version already matches what is in session memory, "
            "no further requests are made and the tool returns immediately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        "Namespace for this skill. Used as the key prefix: "
                        "skill-files.<skill_name>.*"
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "URL of the skill.json file to fetch.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds for each fetch. Must be at least 5.",
                    "minimum": 5,
                },
            },
            "required": ["skill_name", "url", "timeout"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _fetch_text(url: str, timeout: int) -> tuple[str | None, str | None]:
    """Return (text, error). error is None on success."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
        if not (200 <= resp.status_code < 300):
            return None, f"HTTP {resp.status_code}"
        return resp.text, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    skill_name: str = args["skill_name"]
    url: str = args["url"]
    timeout: int = args["timeout"]

    # --- Fetch and parse skill.json ---
    raw, err = _fetch_text(url, timeout)
    if err:
        return f"Error fetching skill.json from '{url}': {err}"

    try:
        skill_json = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"Error: skill.json is not valid JSON: {e}"

    if not isinstance(skill_json, dict):
        return "Error: skill.json must be a JSON object."

    # --- Validate version ---
    version = skill_json.get("version")
    if version is None:
        return "Error: skill.json missing required field 'version'."
    if not isinstance(version, str):
        return "Error: skill.json field 'version' must be a string."
    if not version:
        return "Error: skill.json field 'version' must not be empty."

    # --- Validate files ---
    files = skill_json.get("files")
    if files is None:
        return "Error: skill.json missing required field 'files'."
    if not isinstance(files, dict):
        return "Error: skill.json field 'files' must be an object."
    for k, v in files.items():
        if not isinstance(k, str):
            return "Error: skill.json 'files' keys must all be strings."
        if not isinstance(v, str):
            return f"Error: skill.json 'files' value for key {k!r} must be a string URL."

    # --- Idempotency check ---
    memory = ensure_session_memory(session_data)
    skill_json_key = f"skill-files.{skill_name}.skill.json"
    existing_raw = memory.get(skill_json_key)
    if existing_raw is not None:
        try:
            existing = json.loads(existing_raw)
            if isinstance(existing, dict) and existing.get("version") == version:
                return (
                    f"Skill '{skill_name}' version '{version}' is already loaded. "
                    f"No files fetched."
                )
        except Exception:
            pass  # stale or corrupt entry — reload

    # --- Fetch each declared file ---
    loaded_keys: list[str] = []
    for file_name, file_url in files.items():
        file_text, file_err = _fetch_text(file_url, timeout)
        if file_err:
            return (
                f"Error fetching file '{file_name}' from '{file_url}': {file_err}"
            )
        mem_key = f"skill-files.{skill_name}.{file_name}"
        memory[mem_key] = file_text
        loaded_keys.append(mem_key)

    # --- Persist skill.json itself ---
    memory[skill_json_key] = raw

    files_list = "\n".join(f"  - {k}" for k in loaded_keys)
    return (
        f"Loaded skill '{skill_name}' version '{version}'.\n"
        f"Stored skill manifest as '{skill_json_key}'.\n"
        f"Files stored in session memory ({len(loaded_keys)}):\n{files_list}"
    )
