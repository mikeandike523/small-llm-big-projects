from __future__ import annotations

import os
import logging
from pathlib import Path

from flask import jsonify, request, send_file

from src.ui_connector.app import app
from src.ui_connector.socket_handler_components.session_store import _load_session
from src.ui_connector.socket_handler_components.emit import _emit_backend_log
from src.ui_connector.socket_handler_components.file_download_jobs import (
    DownloadJobError,
    create_download_job,
    get_download_job,
    mark_download_complete,
)

logger = logging.getLogger(__name__)


class ExplorerPathError(ValueError):
    """A requested explorer path is invalid or outside its session root."""


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _resolve_session_path(root_value: str, path_value: str, kind: str) -> Path:
    if not root_value.strip():
        raise ExplorerPathError("Session has no initial working directory")
    try:
        root = Path(root_value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExplorerPathError("Session working directory is unavailable") from exc
    if not root.is_dir():
        raise ExplorerPathError("Session working directory is not a directory")

    requested = Path(path_value)
    if not requested.is_absolute():
        requested = root / requested
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{kind.capitalize()} does not exist") from exc
    except (OSError, RuntimeError) as exc:
        raise ExplorerPathError(
            f"{kind.capitalize()} path could not be resolved"
        ) from exc
    if not _within_root(resolved, root):
        raise PermissionError(
            f"{kind.capitalize()} is outside the session working directory"
        )
    return resolved


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


def read_file(root_value: str, path_value: str) -> dict:
    """Read a UTF-8 text file constrained to the resolved session root."""
    file_path = _resolve_session_path(root_value, path_value, "file")
    if not file_path.is_file():
        raise IsADirectoryError("Requested path is not a file")
    if file_path.stat().st_size > 5 * 1024 * 1024:
        raise ExplorerPathError("File is larger than the 5 MB editor limit")
    raw = file_path.read_bytes()
    if b"\x00" in raw:
        raise ExplorerPathError("Binary files cannot be opened in the text editor")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExplorerPathError("File is not valid UTF-8 text") from exc
    return {"path": _portable(file_path), "content": content}


def write_file(root_value: str, path_value: str, content: str) -> dict:
    """Write UTF-8 text to an existing file inside the session root."""
    file_path = _resolve_session_path(root_value, path_value, "file")
    if not file_path.is_file():
        raise IsADirectoryError("Requested path is not a file")
    encoded = content.encode("utf-8")
    if len(encoded) > 5 * 1024 * 1024:
        raise ExplorerPathError("File is larger than the 5 MB editor limit")
    file_path.write_bytes(encoded)
    return {"path": _portable(file_path), "saved": True}


def _file_request_data():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    path_value = data.get("path")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ExplorerPathError("session_id is required")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ExplorerPathError("path is required")
    session = _load_session(session_id.strip())
    if not session.initial_cwd:
        raise FileNotFoundError("Session not found")
    return data, session, path_value


def _file_error_response(exc: Exception):
    if isinstance(exc, FileNotFoundError):
        return jsonify({"error": str(exc)}), 404
    if isinstance(exc, PermissionError):
        return jsonify({"error": str(exc)}), 403
    if isinstance(exc, FileExistsError):
        return jsonify({"error": str(exc)}), 409
    if isinstance(exc, (DownloadJobError, ExplorerPathError, IsADirectoryError)):
        return jsonify({"error": str(exc)}), 400
    return jsonify({"error": f"Could not access file: {exc}"}), 500


def _emit_file_request_error(
    session_id: object,
    path_value: object,
    exc: Exception,
    source: str = "file-download",
    **extra: object,
) -> None:
    if not isinstance(session_id, str) or not session_id.strip():
        return
    try:
        _emit_backend_log(
            session_id.strip(),
            {
                "source": source,
                "path": path_value,
                **extra,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
    except Exception:
        logger.exception("Could not emit Debug Panel log for %s request", source)


@app.route("/api/file-explorer/read", methods=["POST"])
def api_file_explorer_read():
    try:
        _data, session, path_value = _file_request_data()
        return jsonify(read_file(session.initial_cwd, path_value))
    except (
        ExplorerPathError,
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        OSError,
    ) as exc:
        return _file_error_response(exc)


@app.route("/api/file-explorer/write", methods=["POST"])
def api_file_explorer_write():
    try:
        data, session, path_value = _file_request_data()
        content = data.get("content")
        if not isinstance(content, str):
            raise ExplorerPathError("content must be a string")
        return jsonify(write_file(session.initial_cwd, path_value, content))
    except (
        ExplorerPathError,
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        OSError,
    ) as exc:
        return _file_error_response(exc)


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


@app.route("/api/file-explorer/downloads", methods=["POST"])
def api_file_explorer_create_download():
    data = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id")
    path_value = data.get("path")
    try:
        _data, session, requested_path = _file_request_data()
        root = Path(session.initial_cwd).resolve(strict=True)
        source = _resolve_session_path(session.initial_cwd, requested_path, "download")
        job = create_download_job(session_id.strip(), root, source)
        return jsonify(job.snapshot()), 202
    except (
        DownloadJobError,
        ExplorerPathError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ) as exc:
        _emit_file_request_error(session_id, path_value, exc)
        return _file_error_response(exc)
    except Exception as exc:
        logger.exception("Unexpected error while creating file download")
        _emit_file_request_error(session_id, path_value, exc)
        return _file_error_response(exc)


@app.route("/api/file-explorer/downloads/<job_id>", methods=["GET"])
def api_file_explorer_download_status(job_id: str):
    job = get_download_job(job_id)
    if job is None:
        return jsonify({"error": "Download job not found or expired"}), 404
    return jsonify(job.snapshot())


@app.route("/api/file-explorer/downloads/<job_id>/content", methods=["GET"])
def api_file_explorer_download_content(job_id: str):
    job = get_download_job(job_id)
    if job is None:
        return jsonify({"error": "Download job not found or expired"}), 404
    with job.lock:
        if job.state != "ready" or job.prepared_path is None:
            return jsonify({"error": "Download is not ready"}), 409
        prepared_path = job.prepared_path
        download_name = job.download_name
    try:
        response = send_file(
            prepared_path,
            as_attachment=True,
            download_name=download_name,
            conditional=True,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        _emit_file_request_error(job.session_id, str(job.source), exc)
        return _file_error_response(exc)
    except Exception as exc:
        logger.exception("Unexpected error while starting download %s", job.id)
        _emit_file_request_error(job.session_id, str(job.source), exc)
        return _file_error_response(exc)
    if job.temporary:
        response.call_on_close(lambda: mark_download_complete(job))
    return response
