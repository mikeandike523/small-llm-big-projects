from __future__ import annotations

from flask import jsonify, request

import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.app import app
from src.tools._text_editor_utils import _apply_edits, _parse_patch_file


@app.route("/api/tool-preview/text-editor", methods=["POST"])
def api_text_editor_preview():
    """
    Compute a before/after preview for a text_editor apply_patch call.
    Reads the file or session memory key into a buffer, applies the patch
    in-memory (no side effects), and returns both strings.

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
            before = ""
        except Exception as exc:
            return jsonify({"error": f"Failed to read file: {exc}"}), 500
    else:
        if not session_id:
            return jsonify({"error": "session_id is required when using key"}), 400
        r = _state._get_redis()
        value = r.hget(f"session:{session_id}:memory", key)
        before = value if value is not None else ""

    try:
        hunks = _parse_patch_file(patch)
        after = _apply_edits(before, hunks)
    except Exception as exc:
        return jsonify({"error": f"Failed to apply patch: {exc}"}), 422

    return jsonify({"before": before, "after": after})
