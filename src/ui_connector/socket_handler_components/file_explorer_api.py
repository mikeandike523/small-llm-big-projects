from __future__ import annotations

import os
from pathlib import Path

from flask import jsonify, request

from src.ui_connector.app import app
from src.ui_connector.socket_handler_components.session_store import _load_session


class ExplorerPathError(ValueError):
    """A requested explorer path is invalid or outside its session root."""


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def list_directory(root_value: str, path_value: str | None = None) -> dict:
    """List one directory, constrained to the resolved session root."""
    if not root_value.strip():
        raise ExplorerPathError("Session has no initial working directory")

    try:
        root = Path(root_value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExplorerPathError("Session working directory is unavailable") from exc
    if not root.is_dir():
        raise ExplorerPathError("Session working directory is not a directory")

    requested = Path(path_value) if path_value else root
    if not requested.is_absolute():
        requested = root / requested
    try:
        directory = requested.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError("Directory does not exist") from exc
    except (OSError, RuntimeError) as exc:
        raise ExplorerPathError("Directory path could not be resolved") from exc

    if not _within_root(directory, root):
        raise PermissionError("Directory is outside the session working directory")
    if not directory.is_dir():
        raise NotADirectoryError("Requested path is not a directory")

    entries = []
    with os.scandir(directory) as scan:
        for entry in scan:
            try:
                resolved_entry = Path(entry.path).resolve(strict=True)
                if not _within_root(resolved_entry, root):
                    continue
                is_directory = entry.is_dir(follow_symlinks=True)
            except (FileNotFoundError, OSError, RuntimeError):
                continue
            entries.append(
                {
                    "name": entry.name,
                    "path": _portable(resolved_entry),
                    "kind": "directory" if is_directory else "file",
                }
            )

    entries.sort(
        key=lambda item: (item["kind"] != "directory", item["name"].casefold())
    )
    return {
        "root_path": _portable(root),
        "home_path": _portable(Path.home().resolve()),
        "path": _portable(directory),
        "entries": entries,
    }


@app.route("/api/file-explorer/list", methods=["POST"])
def api_file_explorer_list():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    path_value = data.get("path")
    if not isinstance(session_id, str) or not session_id.strip():
        return jsonify({"error": "session_id is required"}), 400
    if path_value is not None and not isinstance(path_value, str):
        return jsonify({"error": "path must be a string"}), 400

    session = _load_session(session_id.strip())
    if not session.initial_cwd:
        return jsonify({"error": "Session not found"}), 404

    try:
        return jsonify(list_directory(session.initial_cwd, path_value))
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except (ExplorerPathError, NotADirectoryError) as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"error": f"Could not list directory: {exc}"}), 500
