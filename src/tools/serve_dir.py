from __future__ import annotations

from pathlib import Path

from src.tools._path_utils import _resolve_path

DEFINITION = {
    "type": "function",
    "function": {
        "name": "serve_dir",
        "description": "Serve a directory as a static artifact in the background. Returns its permanent artifact id and URL. Serving does not open the artifact automatically; call open_artifact explicitly.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Directory path, relative to the session working directory or absolute."}, "rewrite_rule": {"type": "string", "enum": ["SPA_INDEX"], "description": "Optional approved rewrite. SPA_INDEX serves the artifact root index.html for missing clean-URL routes."}}, "required": ["path"], "additionalProperties": False},
    },
}


def needs_approval(args: dict, session_data=None, special_resources=None) -> bool:
    from src.tools._approval import ApprovalContext, is_auto_accept_edits, is_full_auto, needs_path_approval
    if is_full_auto(special_resources):
        return False
    if is_auto_accept_edits(special_resources):
        return needs_path_approval(args.get("path"), ctx=ApprovalContext.from_special_resources(special_resources))
    return True


def execute(args: dict, session_data=None, special_resources=None) -> str:
    sr = special_resources or {}
    directory = Path(_resolve_path(args["path"], sr.get("session_current_working_dir")))
    if not directory.is_dir():
        return f"Error: directory does not exist: {directory}"
    try:
        from src.utils.artifact_client import artifact_url, create_artifact
        record = create_artifact(str(directory), sr.get("session_id", ""), args.get("rewrite_rule"))
        rewrite = record.get("rewrite_rule") or "none"
        return f"Artifact serving started. id={record['id']} url={artifact_url(record['id'])} directory={record['directory']} rewrite_rule={rewrite}"
    except Exception as exc:
        return f"Error: {exc}"
