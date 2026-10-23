"""Rename/delete routes for the session file explorer's context menu."""

from __future__ import annotations

import logging
import os
import shutil
import stat
from pathlib import Path

from flask import jsonify, request

from src.ui_connector.app import app
from src.ui_connector.socket_handler_components.file_explorer_api import (
    ExplorerPathError,
    _emit_file_request_error,
    _file_error_response,
    _file_request_data,
    _portable,
    _resolve_session_path,
)

logger = logging.getLogger(__name__)


def _resolve_mutable_entry(root_value: str, path_value: str) -> Path:
    """Resolve an entry that may be renamed/deleted (never the root itself)."""
    entry = _resolve_session_path(root_value, path_value, "entry")
    if entry == Path(root_value).resolve(strict=True):
        raise PermissionError("The session working directory cannot be modified")
    return entry


def _validate_new_name(new_name: object) -> str:
    if not isinstance(new_name, str) or not new_name.strip():
        raise ExplorerPathError("new_name is required")
    if new_name != new_name.strip():
        raise ExplorerPathError("Name cannot start or end with whitespace")
    if new_name in (".", "..") or "/" in new_name or "\\" in new_name:
        raise ExplorerPathError(f"Invalid name: {new_name!r}")
    return new_name


def rename_entry(root_value: str, path_value: str, new_name: object) -> dict:
    """Rename a file or directory in place (same parent directory)."""
    source = _resolve_mutable_entry(root_value, path_value)
    name = _validate_new_name(new_name)
    target = source.parent / name
    kind = "directory" if source.is_dir() else "file"
    if name != source.name:
        # Case-only renames on case-insensitive filesystems "exist" already.
        if os.path.lexists(target) and not (
            target.exists() and os.path.samefile(source, target)
        ):
            raise FileExistsError(f"An entry named {name!r} already exists")
        os.rename(source, target)
    return {
        "old_path": _portable(source),
        "path": _portable(target.resolve()),
        "name": name,
        "kind": kind,
    }


def _clear_readonly_and_retry(function, path, _exc) -> None:
    # Windows refuses to delete read-only files (e.g. git objects).
    os.chmod(path, stat.S_IWRITE)
    function(path)


def delete_entry(root_value: str, path_value: str) -> dict:
    """Permanently delete a file, or a directory with all its contents."""
    entry = _resolve_mutable_entry(root_value, path_value)
    if entry.is_dir():
        shutil.rmtree(entry, onexc=_clear_readonly_and_retry)
        kind = "directory"
    else:
        try:
            entry.unlink()
        except PermissionError:
            os.chmod(entry, stat.S_IWRITE)
            entry.unlink()
        kind = "file"
    return {"path": _portable(entry), "kind": kind, "deleted": True}


def _request_body() -> dict:
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


@app.route("/api/file-explorer/rename", methods=["POST"])
def api_file_explorer_rename():
    body = _request_body()
    try:
        _data, session, path_value = _file_request_data()
        return jsonify(
            rename_entry(session.initial_cwd, path_value, body.get("new_name"))
        )
    except Exception as exc:
        if not isinstance(exc, (ExplorerPathError, OSError)):
            logger.exception("Unexpected error while renaming %s", body.get("path"))
        _emit_file_request_error(
            body.get("session_id"),
            body.get("path"),
            exc,
            "file-rename",
            new_name=body.get("new_name"),
        )
        return _file_error_response(exc)


@app.route("/api/file-explorer/delete", methods=["POST"])
def api_file_explorer_delete():
    body = _request_body()
    try:
        _data, session, path_value = _file_request_data()
        return jsonify(delete_entry(session.initial_cwd, path_value))
    except Exception as exc:
        if not isinstance(exc, (ExplorerPathError, OSError)):
            logger.exception("Unexpected error while deleting %s", body.get("path"))
        _emit_file_request_error(
            body.get("session_id"), body.get("path"), exc, "file-delete"
        )
        return _file_error_response(exc)
