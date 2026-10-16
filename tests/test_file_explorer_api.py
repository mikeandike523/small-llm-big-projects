import io
import time
import zipfile
from pathlib import Path

import pytest

from src.ui_connector.app import app
from src.utils.session_model import Session
import src.ui_connector.socket_handler_components.file_explorer_api as explorer_api
import src.ui_connector.socket_handler_components.file_download_jobs as download_jobs
from src.ui_connector.socket_handler_components.file_explorer_api import (
    list_directory,
    read_file,
    write_file,
)


def test_list_directory_sorts_folders_before_files(tmp_path: Path) -> None:
    (tmp_path / "z-folder").mkdir()
    (tmp_path / "a-folder").mkdir()
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "A.txt").write_text("a", encoding="utf-8")

    result = list_directory(str(tmp_path))

    assert [(item["kind"], item["name"]) for item in result["entries"]] == [
        ("directory", "a-folder"),
        ("directory", "z-folder"),
        ("file", "A.txt"),
        ("file", "z.txt"),
    ]


def test_list_directory_accepts_descendant(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (child / "inside.py").write_text("", encoding="utf-8")

    result = list_directory(str(tmp_path), str(child))

    assert result["path"] == str(child.resolve()).replace("\\", "/")
    assert result["entries"][0]["name"] == "inside.py"


def test_list_directory_rejects_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(PermissionError):
        list_directory(str(root), str(tmp_path))


def test_list_directory_rejects_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        list_directory(str(tmp_path), str(file_path))


def test_file_explorer_route_lists_session_root(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    monkeypatch.setattr(
        explorer_api,
        "_load_session",
        lambda session_id: Session(session_id=session_id, initial_cwd=str(tmp_path)),
    )

    response = app.test_client().post(
        "/api/file-explorer/list", json={"session_id": "session-1"}
    )

    assert response.status_code == 200
    assert response.get_json()["entries"][0]["name"] == "src"


def test_file_explorer_route_rejects_path_outside_root(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(
        explorer_api,
        "_load_session",
        lambda session_id: Session(session_id=session_id, initial_cwd=str(root)),
    )

    response = app.test_client().post(
        "/api/file-explorer/list",
        json={"session_id": "session-1", "path": str(tmp_path)},
    )

    assert response.status_code == 403


def test_read_and_write_file_inside_root(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("before", encoding="utf-8")

    result = read_file(str(tmp_path), str(file_path))
    assert result["content"] == "before"

    write_file(str(tmp_path), str(file_path), "after\n")
    assert file_path.read_text(encoding="utf-8") == "after\n"


def test_read_file_rejects_binary_and_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    binary = root / "image.bin"
    binary.write_bytes(b"data\x00more")
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")

    with pytest.raises(explorer_api.ExplorerPathError):
        read_file(str(root), str(binary))
    with pytest.raises(PermissionError):
        read_file(str(root), str(outside))


def test_file_editor_routes_read_and_write(tmp_path: Path, monkeypatch) -> None:
    file_path = tmp_path / "editable.ts"
    file_path.write_text("const value = 1;", encoding="utf-8")
    monkeypatch.setattr(
        explorer_api,
        "_load_session",
        lambda session_id: Session(session_id=session_id, initial_cwd=str(tmp_path)),
    )
    client = app.test_client()

    read_response = client.post(
        "/api/file-explorer/read",
        json={"session_id": "session-1", "path": str(file_path)},
    )
    write_response = client.post(
        "/api/file-explorer/write",
        json={
            "session_id": "session-1",
            "path": str(file_path),
            "content": "const value = 2;",
        },
    )

    assert read_response.status_code == 200
    assert read_response.get_json()["content"] == "const value = 1;"
    assert write_response.status_code == 200
    assert file_path.read_text(encoding="utf-8") == "const value = 2;"


def _download_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        explorer_api,
        "_load_session",
        lambda session_id: Session(session_id=session_id, initial_cwd=str(tmp_path)),
    )
    return app.test_client()


def _wait_for_download(client, download_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/file-explorer/downloads/{download_id}")
        assert response.status_code == 200
        payload = response.get_json()
        if payload["state"] in {"ready", "failed"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("Download job did not reach a terminal preparation state")


def test_file_download_is_immediately_ready(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "report.txt"
    source.write_text("download contents", encoding="utf-8")
    client = _download_client(tmp_path, monkeypatch)

    created = client.post(
        "/api/file-explorer/downloads",
        json={"session_id": "session-1", "path": str(source)},
    )

    assert created.status_code == 202
    payload = created.get_json()
    assert payload["state"] == "ready"
    assert payload["archive_bytes"] == len(b"download contents")
    downloaded = client.get(payload["content_url"])
    assert downloaded.status_code == 200
    assert downloaded.data == b"download contents"
    assert downloaded.content_length == len(b"download contents")
    assert "report.txt" in downloaded.headers["Content-Disposition"]


def test_directory_download_builds_zip_on_disk(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "project"
    empty = folder / "empty"
    nested = folder / "src"
    empty.mkdir(parents=True)
    nested.mkdir()
    source_file = nested / "main.py"
    source_file.write_text("print('hello')\n", encoding="utf-8")
    client = _download_client(tmp_path, monkeypatch)

    created = client.post(
        "/api/file-explorer/downloads",
        json={"session_id": "session-1", "path": str(folder)},
    )
    payload = _wait_for_download(client, created.get_json()["download_id"])

    assert payload["state"] == "ready"
    assert payload["download_name"] == "project.zip"
    downloaded = client.get(payload["content_url"])
    assert downloaded.status_code == 200
    assert downloaded.content_length == len(downloaded.data)
    with zipfile.ZipFile(io.BytesIO(downloaded.data)) as archive:
        assert "project/" in archive.namelist()
        assert "project/empty/" in archive.namelist()
        assert archive.read("project/src/main.py") == source_file.read_bytes()
    downloaded.close()


def test_directory_job_reports_limit_failure_to_debug_panel(
    tmp_path: Path, monkeypatch
) -> None:
    folder = tmp_path / "large"
    folder.mkdir()
    (folder / "content.bin").write_bytes(b"content that exceeds a tiny test cap")
    emitted = []
    monkeypatch.setattr(download_jobs, "MAX_ARCHIVE_BYTES", 20)
    monkeypatch.setattr(
        download_jobs.tempfile,
        "mkstemp",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("oversized archive should fail before creating a temp file")
        ),
    )
    monkeypatch.setattr(
        download_jobs,
        "_emit_backend_log",
        lambda session_id, content: emitted.append((session_id, content)),
    )
    client = _download_client(tmp_path, monkeypatch)

    created = client.post(
        "/api/file-explorer/downloads",
        json={"session_id": "session-1", "path": str(folder)},
    )
    payload = _wait_for_download(client, created.get_json()["download_id"])

    assert payload["state"] == "failed"
    assert "2 GiB download limit" in payload["error"]
    assert len(emitted) == 1
    assert emitted[0][0] == "session-1"
    assert emitted[0][1]["source"] == "file-download"
