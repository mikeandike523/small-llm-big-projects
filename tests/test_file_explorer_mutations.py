import os
import stat

import pytest

from src.ui_connector.app import app
from src.utils.session_model import Session
import src.ui_connector.socket_handler_components.file_explorer_api as explorer_api
from src.ui_connector.socket_handler_components.file_explorer_api import (
    ExplorerPathError,
)
from src.ui_connector.socket_handler_components.file_explorer_mutations import (
    delete_entry,
    rename_entry,
)


def test_rename_file(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    result = rename_entry(str(tmp_path), str(tmp_path / "a.txt"), "b.txt")
    assert result["name"] == "b.txt"
    assert result["kind"] == "file"
    assert result["path"].endswith("/b.txt")
    assert (tmp_path / "b.txt").read_text() == "x"
    assert not (tmp_path / "a.txt").exists()


def test_rename_directory_keeps_contents(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f.txt").write_text("x")
    result = rename_entry(str(tmp_path), str(tmp_path / "d"), "e")
    assert result["kind"] == "directory"
    assert (tmp_path / "e" / "f.txt").read_text() == "x"


def test_rename_case_only(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    rename_entry(str(tmp_path), str(tmp_path / "a.txt"), "A.txt")
    assert os.listdir(tmp_path) == ["A.txt"]


def test_rename_refuses_existing_target(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    with pytest.raises(FileExistsError):
        rename_entry(str(tmp_path), str(tmp_path / "a.txt"), "b.txt")
    assert (tmp_path / "b.txt").read_text() == "b"


@pytest.mark.parametrize("name", ["", " x", "..", "a/b", r"a\b", None])
def test_rename_rejects_invalid_names(tmp_path, name):
    (tmp_path / "a.txt").write_text("a")
    with pytest.raises(ExplorerPathError):
        rename_entry(str(tmp_path), str(tmp_path / "a.txt"), name)


def test_root_cannot_be_renamed_or_deleted(tmp_path):
    with pytest.raises(PermissionError):
        rename_entry(str(tmp_path), str(tmp_path), "other")
    with pytest.raises(PermissionError):
        delete_entry(str(tmp_path), str(tmp_path))
    assert tmp_path.exists()


def test_paths_outside_root_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("x")
    with pytest.raises(PermissionError):
        delete_entry(str(root), str(tmp_path / "outside.txt"))
    assert (tmp_path / "outside.txt").exists()


def test_delete_readonly_file(tmp_path):
    target = tmp_path / "ro.txt"
    target.write_text("x")
    os.chmod(target, stat.S_IREAD)
    assert delete_entry(str(tmp_path), str(target))["kind"] == "file"
    assert not target.exists()


def test_delete_directory_with_readonly_contents(tmp_path):
    (tmp_path / "d" / "sub").mkdir(parents=True)
    ro = tmp_path / "d" / "sub" / "ro.txt"
    ro.write_text("x")
    os.chmod(ro, stat.S_IREAD)
    assert delete_entry(str(tmp_path), str(tmp_path / "d"))["kind"] == "directory"
    assert not (tmp_path / "d").exists()


def test_delete_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        delete_entry(str(tmp_path), str(tmp_path / "nope"))


def _client(tmp_path, monkeypatch, logs):
    monkeypatch.setattr(
        explorer_api,
        "_load_session_info",
        lambda session_id: Session(session_id=session_id, initial_cwd=str(tmp_path)),
    )
    monkeypatch.setattr(
        explorer_api,
        "_emit_backend_log",
        lambda session_id, content: logs.append((session_id, content)),
    )
    return app.test_client()


def test_rename_and_delete_routes(tmp_path, monkeypatch):
    logs = []
    client = _client(tmp_path, monkeypatch, logs)
    (tmp_path / "a.txt").write_text("x")
    response = client.post(
        "/api/file-explorer/rename",
        json={"session_id": "s", "path": str(tmp_path / "a.txt"), "new_name": "b.txt"},
    )
    assert response.status_code == 200
    new_path = response.get_json()["path"]
    response = client.post(
        "/api/file-explorer/delete", json={"session_id": "s", "path": new_path}
    )
    assert response.status_code == 200
    assert response.get_json()["deleted"] is True
    assert list(tmp_path.iterdir()) == []
    assert logs == []


def test_route_failures_are_logged_to_debug_panel(tmp_path, monkeypatch):
    logs = []
    client = _client(tmp_path, monkeypatch, logs)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    response = client.post(
        "/api/file-explorer/rename",
        json={"session_id": "s", "path": str(tmp_path / "a.txt"), "new_name": "b.txt"},
    )
    assert response.status_code == 409
    response = client.post(
        "/api/file-explorer/delete",
        json={"session_id": "s", "path": str(tmp_path / "missing.txt")},
    )
    assert response.status_code == 404
    assert [content["source"] for _sid, content in logs] == [
        "file-rename",
        "file-delete",
    ]
    assert logs[0][1]["new_name"] == "b.txt"
    assert "FileExistsError" in logs[0][1]["error"]
