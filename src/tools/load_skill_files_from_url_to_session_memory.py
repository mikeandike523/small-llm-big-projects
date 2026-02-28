from __future__ import annotations

import json

import httpx

from src.utils.http.helpers import ensure_session_memory

LEAVE_OUT = "PARAMS_ONLY"

DEFAULT_TIMEOUT = 30  # informational; actual value comes from args
TIMEOUT_HINT = None

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "load_skill_files_from_url_to_session_memory",
        "description": (
            "Fetch a skill.json from a URL and load all its declared files into session memory. "
            "By default the skill.json must have a top-level 'version' string field and a "
            "top-level 'files' object mapping file names to fetch URLs. "
            "Use version_path / files_path to override where those fields are located when "
            "the JSON structure differs (e.g. version_path='meta.version', files_path='assets'). "
            "Each file is stored as skill-files.<skill_name>.<file_name>. "
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
                "version_path": {
                    "type": "string",
                    "description": (
                        "Dot-delimited path to the version field within the fetched JSON object. "
                        "Defaults to 'version' (top-level). "
                        "Example: 'meta.version' resolves to obj['meta']['version']."
                    ),
                },
                "files_path": {
                    "type": "string",
                    "description": (
                        "Dot-delimited path to the files object within the fetched JSON object. "
                        "Defaults to 'files' (top-level). "
                        "Example: 'assets.urls' resolves to obj['assets']['urls']."
                    ),
                },
            },
            "required": ["skill_name", "url", "timeout"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _get_by_path(obj: object, path: str | None, field_label: str) -> tuple[object, str | None]:
    """Drill into obj using a dot-delimited path. Returns (value, error)."""
    if not path:
        return obj, None
    parts = path.split(".")
    current = obj
    traversed: list[str] = []
    for part in parts:
        if not isinstance(current, dict):
            loc = ".".join(traversed) if traversed else "<root>"
            return None, f"path '{path}': '{loc}' is not an object while resolving {field_label}"
        if part not in current:
            return None, f"path '{path}': key '{part}' not found while resolving {field_label}"
        current = current[part]
        traversed.append(part)
    return current, None


def _fetch_text(url: str, timeout: int) -> tuple[str | None, str | None]:
    """Return (text, error). error is None on success. Propagates httpx.TimeoutException."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
        if not (200 <= resp.status_code < 300):
            return None, f"HTTP {resp.status_code}"
        return resp.text, None
    except httpx.TimeoutException:
        raise  # let execute() convert to ToolTimeoutError
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    skill_name: str = args["skill_name"]
    url: str = args["url"]
    timeout: int = args["timeout"]
    version_path: str | None = args.get("version_path") or None
    files_path: str | None = args.get("files_path") or None

    # --- Fetch and parse skill.json ---
    try:
        raw, err = _fetch_text(url, timeout)
    except httpx.TimeoutException:
        from src.utils.exceptions import ToolTimeoutError
        raise ToolTimeoutError("load_skill_files_from_url_to_session_memory", timeout)
    if err:
        return f"Error fetching skill.json from '{url}': {err}"

    try:
        skill_json = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"Error: skill.json is not valid JSON: {e}"

    if not isinstance(skill_json, dict):
        return "Error: skill.json must be a JSON object."

    # --- Resolve version ---
    effective_version_path = version_path or "version"
    version, path_err = _get_by_path(skill_json, effective_version_path, "version")
    if path_err:
        return f"Error: {path_err}."
    if version is None:
        return f"Error: skill.json missing required field at '{effective_version_path}'."
    if not isinstance(version, str):
        return f"Error: skill.json field at '{effective_version_path}' must be a string."
    if not version:
        return f"Error: skill.json field at '{effective_version_path}' must not be empty."

    # --- Resolve files ---
    effective_files_path = files_path or "files"
    files, path_err = _get_by_path(skill_json, effective_files_path, "files")
    if path_err:
        return f"Error: {path_err}."
    if files is None:
        return f"Error: skill.json missing required field at '{effective_files_path}'."
    if not isinstance(files, dict):
        return f"Error: skill.json field at '{effective_files_path}' must be an object."
    for k, v in files.items():
        if not isinstance(k, str):
            return f"Error: skill.json '{effective_files_path}' keys must all be strings."
        if not isinstance(v, str):
            return f"Error: skill.json '{effective_files_path}' value for key {k!r} must be a string URL."

    # --- Idempotency check ---
    memory = ensure_session_memory(session_data)
    skill_json_key = f"skill-files.{skill_name}.skill.json"
    existing_raw = memory.get(skill_json_key)
    if existing_raw is not None:
        try:
            existing = json.loads(existing_raw)
            if isinstance(existing, dict):
                existing_version, _ = _get_by_path(existing, effective_version_path, "version")
                if existing_version == version:
                    return (
                        f"Skill '{skill_name}' version '{version}' is already loaded. "
                        f"No files fetched."
                    )
        except Exception:
            pass  # stale or corrupt entry — reload

    # --- Fetch each declared file ---
    loaded_keys: list[str] = []
    for file_name, file_url in files.items():
        try:
            file_text, file_err = _fetch_text(file_url, timeout)
        except httpx.TimeoutException:
            from src.utils.exceptions import ToolTimeoutError
            raise ToolTimeoutError("load_skill_files_from_url_to_session_memory", timeout)
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
