from pathlib import Path

import pytest

from src.ui_connector.app import app
from src.utils.session_model import Session
import src.ui_connector.socket_handler_components.file_explorer_api as explorer_api
from src.ui_connector.socket_handler_components.file_explorer_api import (
    list_directory,
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
