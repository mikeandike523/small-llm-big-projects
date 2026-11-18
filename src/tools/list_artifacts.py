from __future__ import annotations

DEFINITION = {"type": "function", "function": {"name": "list_artifacts", "description": "List static artifacts currently served by this session.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}


def needs_approval(args: dict, session_data=None, special_resources=None) -> bool:
    return False


def execute(args: dict, session_data=None, special_resources=None) -> str:
    try:
        from src.utils.artifact_client import artifact_url, list_artifacts
        session_id = (special_resources or {}).get("session_id", "")
        records = [r for r in list_artifacts() if r.get("session_id") == session_id and r.get("status") == "active"]
        if not records:
            return "No active artifacts."
        return "\n".join(f"id={r['id']} url={artifact_url(r['id'])} directory={r['directory']}" for r in records)
    except Exception as exc:
        return f"Error: {exc}"
