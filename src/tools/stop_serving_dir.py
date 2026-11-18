from __future__ import annotations

DEFINITION = {"type": "function", "function": {"name": "stop_serving_dir", "description": "Stop serving an artifact by id. Its URL is permanently retired and returns HTTP 410.", "parameters": {"type": "object", "properties": {"artifact_id": {"type": "string", "description": "Artifact id returned by serve_dir."}}, "required": ["artifact_id"], "additionalProperties": False}}}


def needs_approval(args: dict, session_data=None, special_resources=None) -> bool:
    return False


def execute(args: dict, session_data=None, special_resources=None) -> str:
    try:
        from src.utils.artifact_client import list_artifacts, stop_artifact
        session_id = (special_resources or {}).get("session_id", "")
        records = list_artifacts()
        record = next((r for r in records if r.get("id") == args["artifact_id"]), None)
        if record is None or record.get("session_id") != session_id:
            return "Error: artifact not found in this session."
        stop_artifact(args["artifact_id"])
        return f"Artifact stopped: {args['artifact_id']} (its URL now returns HTTP 410)."
    except Exception as exc:
        return f"Error: {exc}"
