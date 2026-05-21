from __future__ import annotations

from flask import jsonify, request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import app
from src.tools._text_editor_utils import _apply_edits, _parse_patch_file


def _read_redis_memory(session_id: str, key: str) -> str | None:
    """Return the session memory value for key, or None if absent."""
    r = _state._get_redis()
    return r.hget(f"session:{session_id}:memory", key)


@app.route("/api/tool-preview/text-editor", methods=["POST"])
def api_text_editor_preview():
    """
    Compute a before/after preview for a text_editor apply_patch call.
    Returns {exists: false} when the source does not exist (file missing or
    memory key absent) — the real tool would error in those cases too.

    Body JSON:
      filepath    str?  — path on disk (mutually exclusive with key)
      key         str?  — session memory key (requires session_id)
      session_id  str?  — required when key is provided
      patch       str   — unified diff string
    """
    data = request.get_json(force=True, silent=True) or {}
    filepath = data.get("filepath") or None
    key = data.get("key") or None
    session_id = data.get("session_id") or None
    patch = data.get("patch") or ""

    if not patch:
        return jsonify({"error": "patch is required"}), 400
    if not filepath and not key:
        return jsonify({"error": "filepath or key is required"}), 400

    if filepath:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                before = fh.read()
        except FileNotFoundError:
            return jsonify({"exists": False})
        except Exception as exc:
            return jsonify({"error": f"Failed to read file: {exc}"}), 500
    else:
        if not session_id:
            return jsonify({"error": "session_id is required when using key"}), 400
        before = _read_redis_memory(session_id, key)
        if before is None:
            return jsonify({"exists": False})

    try:
        hunks = _parse_patch_file(patch)
        after = _apply_edits(before, hunks)
    except Exception as exc:
        return jsonify({"error": f"Failed to apply patch: {exc}"}), 422

    return jsonify({"exists": True, "before": before, "after": after})


@app.route("/api/tool-preview/write-text-file", methods=["POST"])
def api_write_text_file_preview():
    """
    Compute a before/after preview for a write_text_file call.
    Returns {exists: false} when the target path does not yet exist.

    Body JSON:
      path                str   — file path on disk
      content             str?  — new content (mutually exclusive with session_memory_key)
      session_memory_key  str?  — session memory key holding new content (requires session_id)
      session_id          str?  — required when session_memory_key is provided
    """
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path") or ""
    content = data.get("content")
    session_memory_key = data.get("session_memory_key") or None
    session_id = data.get("session_id") or None

    if not path:
        return jsonify({"error": "path is required"}), 400

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            before = fh.read()
    except FileNotFoundError:
        return jsonify({"exists": False})
    except Exception as exc:
        return jsonify({"error": f"Failed to read file: {exc}"}), 500

    if content is not None:
        after = content
    elif session_memory_key:
        if not session_id:
            return jsonify({"error": "session_id is required when using session_memory_key"}), 400
        after = _read_redis_memory(session_id, session_memory_key)
        if after is None:
            return jsonify({"error": f"Session memory key {session_memory_key!r} not found"}), 404
    else:
        return jsonify({"error": "content or session_memory_key is required"}), 400

    return jsonify({"exists": True, "before": before, "after": after})


@app.route("/api/tool-preview/session-memory", methods=["POST"])
def api_session_memory_preview():
    """
    Compute a before/after preview for a session_memory set call.
    Returns {exists: false} when the key does not yet exist in session memory.

    Body JSON:
      key         str  — session memory key
      value       str  — new value being set
      session_id  str  — required to look up the existing value
    """
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("key") or ""
    value = data.get("value")
    session_id = data.get("session_id") or ""

    if not key or not session_id:
        return jsonify({"error": "key and session_id are required"}), 400
    if value is None:
        return jsonify({"error": "value is required"}), 400

    before = _read_redis_memory(session_id, key)
    if before is None:
        return jsonify({"exists": False})

    return jsonify({"exists": True, "before": before, "after": value})
