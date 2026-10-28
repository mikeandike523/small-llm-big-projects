"""Session-less folder browsing for the New Session dialog's folder picker.

Used when the UI is not running inside the desktop app (which has a native
picker instead), e.g. on a remote server reached from a browser. Unlike
``file_explorer_api`` these routes are not scoped to a session root: the
dialog runs before any session exists. They only list folder names and never
read or change file contents.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from flask import jsonify, request

from src.ui_connector.app import app
from src.utils.cwd_policy import check_initial_cwd
from src.utils.folder_shortcuts import get_folder_shortcuts

MAX_FOLDER_ENTRIES = 2000


class FolderBrowseError(Exception):
    def __init__(self, message: str, status: int, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _portable(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _require_home() -> Path:
    """The picker always starts at home, so a missing home is a hard error."""
    try:
        home = Path.home()
    except (RuntimeError, KeyError, OSError) as exc:
        raise FolderBrowseError(
            f"Could not determine the server's home directory: {exc}",
            500,
            "home_unavailable",
        ) from exc
    if not home.is_dir():
        raise FolderBrowseError(
            f"The server's home directory does not exist: {_portable(home)}",
            500,
            "home_unavailable",
        )
    return home


def _target_directory(raw: object, home: Path) -> Path:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return home
    if not isinstance(raw, str):
        raise FolderBrowseError("path must be a string", 400)
    text = raw.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise FolderBrowseError("Path contains invalid characters.", 400)
    if text == "~" or text.startswith(("~/", "~\\")):
        text = str(home) + text[1:]
    if os.name == "nt" and _portable(text).startswith("//"):
        raise FolderBrowseError("Network (UNC) paths cannot be browsed.", 400)
    if not os.path.isabs(text):
        raise FolderBrowseError("Enter an absolute path (or one starting with ~).", 400)
    path = Path(os.path.normpath(text))
    if not path.exists():
        raise FolderBrowseError("Folder does not exist.", 404)
    # Typing a file path jumps to the folder that contains it.
    return path if path.is_dir() else path.parent


def _is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes
        except OSError:
            return False
        return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)
    return False


def list_folders(directory: Path, show_hidden: bool) -> tuple[list[dict], bool]:
    entries: list[dict] = []
    with os.scandir(directory) as scan:
        for entry in scan:
            try:
                if not entry.is_dir(follow_symlinks=True):
                    continue
            except OSError:
                continue
            if not show_hidden and _is_hidden(entry):
                continue
            entries.append({"name": entry.name, "path": _portable(entry.path)})
    entries.sort(key=lambda item: item["name"].casefold())
    truncated = len(entries) > MAX_FOLDER_ENTRIES
    return entries[:MAX_FOLDER_ENTRIES], truncated


@app.route("/api/folder-browser/list", methods=["POST"])
def api_folder_browser_list():
    """List the sub-folders of one folder.

    Body: {"path": str?  (absolute or ~-relative; defaults to home),
           "show_hidden": bool?}
    Returns: {"home_path", "path", "parent_path", "entries": [{"name", "path"}],
              "truncated", "shortcuts": [{"label", "path"}]}
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        home = _require_home()
        directory = _target_directory(data.get("path"), home)
        try:
            entries, truncated = list_folders(directory, bool(data.get("show_hidden")))
        except PermissionError as exc:
            raise FolderBrowseError("Permission denied.", 403) from exc
        except OSError as exc:
            raise FolderBrowseError(f"Could not list folder: {exc}", 500) from exc
    except FolderBrowseError as exc:
        body = {"error": str(exc)}
        if exc.code:
            body["code"] = exc.code
        return jsonify(body), exc.status

    parent = directory.parent
    return jsonify(
        {
            "home_path": _portable(home),
            "path": _portable(directory),
            "parent_path": None if parent == directory else _portable(parent),
            "entries": entries,
            "truncated": truncated,
            "shortcuts": get_folder_shortcuts(home),
        }
    )


@app.route("/api/folder-check", methods=["POST"])
def api_folder_check():
    """Classify a candidate session cwd without creating anything.

    Body: {"path": str, "session_id": str?}
    Returns the ``CwdCheck`` JSON: {"status": "ok"|"warning"|"error",
    "resolved_path", "message", "reason"}.
    """
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    check = check_initial_cwd(
        data.get("path"), session_id if isinstance(session_id, str) else None
    )
    return jsonify(check.to_json())
