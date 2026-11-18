from __future__ import annotations

DEFINITION = {"type": "function", "function": {"name": "open_artifact", "description": "Open a served artifact for the user in the artifact viewer. Use the artifact id returned by serve_dir.", "parameters": {"type": "object", "properties": {"artifact_id": {"type": "string", "description": "Artifact id returned by serve_dir."}}, "required": ["artifact_id"], "additionalProperties": False}}}


def needs_approval(args: dict, session_data=None, special_resources=None) -> bool:
    return False


def execute(args: dict, session_data=None, special_resources=None) -> str:
    try:
        from src.utils.artifact_client import artifact_url, list_artifacts
        session_id = (special_resources or {}).get("session_id", "")
        record = next((r for r in list_artifacts() if r.get("id") == args["artifact_id"] and r.get("session_id") == session_id and r.get("status") == "active"), None)
        if record is None:
            return "Error: artifact not found in this session."
        url = artifact_url(record["id"])
        opener = (special_resources or {}).get("open_artifact")
        if opener:
            opener(url, record["id"])
        return f"Artifact opened: {url}"
    except Exception as exc:
        return f"Error: {exc}"
