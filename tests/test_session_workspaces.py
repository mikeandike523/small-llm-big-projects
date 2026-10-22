"""Per-session workspace/scratchpad folders, prompt placeholders, and the
scratchpad's approval semantics (it is approved exactly like the session CWD)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import src.tools._approval as approval
import src.ui_connector.socket_handler_components.http_api as http_api
import src.ui_connector.socket_handler_components.session_setup  # noqa: F401  (registers routes)
from src.logic.prompt_placeholders import PlaceholderContext, interpolate_placeholders
from src.logic.system_prompt import build_system_prompt
from src.tools import check_needs_approval
from src.ui_connector.app import app
from src.utils import session_dirs
from src.utils.env_info import format_environment_info


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------


def test_session_folder_paths(fake_home: Path) -> None:
    sid = str(uuid.uuid4())
    home = str(fake_home).replace("\\", "/")
    assert (
        session_dirs.get_session_workspace_dir(sid) == f"{home}/.slbp/workspaces/{sid}"
    )
    assert (
        session_dirs.get_session_scratchpad_dir(sid)
        == f"{home}/.slbp/scratchpads/{sid}"
    )


def test_ensure_creates_scratchpad_and_session_workspace(fake_home: Path) -> None:
    sid = str(uuid.uuid4())
    workspace = session_dirs.get_session_workspace_dir(sid)
    session_dirs.ensure_session_dirs(sid, workspace)
    assert Path(session_dirs.get_session_scratchpad_dir(sid)).is_dir()
    assert Path(workspace).is_dir()


def test_ensure_never_recreates_a_missing_project_folder(
    fake_home: Path, tmp_path: Path
) -> None:
    sid = str(uuid.uuid4())
    missing_project = tmp_path / "deleted-project"
    session_dirs.ensure_session_dirs(sid, str(missing_project))
    assert not missing_project.exists()
    assert Path(session_dirs.get_session_scratchpad_dir(sid)).is_dir()


def test_delete_scratchpad_only_for_valid_ids(fake_home: Path) -> None:
    sid = str(uuid.uuid4())
    session_dirs.ensure_session_dirs(sid, None)
    scratch = Path(session_dirs.get_session_scratchpad_dir(sid))
    (scratch / "tmp.txt").write_text("x", encoding="utf-8")
    session_dirs.delete_session_scratchpad(sid)
    assert not scratch.exists()

    # A traversal-shaped id must never reach rmtree.
    root = Path(session_dirs.get_session_scratchpads_root())
    session_dirs.delete_session_scratchpad("..")
    assert root.is_dir()


@pytest.mark.parametrize(
    "value, ok",
    [
        (str(uuid.uuid4()), True),
        (str(uuid.uuid4()).upper(), False),
        ("../etc", False),
        ("", False),
        (None, False),
    ],
)
def test_is_valid_session_id(value, ok) -> None:
    assert session_dirs.is_valid_session_id(value) is ok


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


def test_interpolation_known_unknown_and_lowercase() -> None:
    reported: list[tuple[str, str]] = []
    ctx = PlaceholderContext(
        values={"SCRATCHPAD_PATH": "/s"},
        on_unknown=lambda name, source: reported.append((name, source)),
    )
    text = "a {{ SCRATCHPAD_PATH }} b {{SCRATCHPAD_PATH}} c {{ NOPE }} {{ NOPE }} d {{ name }}"
    out = interpolate_placeholders(text, ctx, source="x.md")
    assert out == "a /s b /s c {{ NOPE }} {{ NOPE }} d {{ name }}"
    assert reported == [("NOPE", "x.md")]


def test_interpolation_without_context_is_identity() -> None:
    assert interpolate_placeholders("{{ HOME }}", None, source="x") == "{{ HOME }}"


def test_system_prompt_and_autoload_skills_are_interpolated(tmp_path: Path) -> None:
    skill = tmp_path / "s.md"
    skill.write_text("# S\n\nScratch at {{ SCRATCHPAD_PATH }}\n", encoding="utf-8")
    ctx = PlaceholderContext(values={"SCRATCHPAD_PATH": "/scratch/abc"})
    prompt = build_system_prompt(
        autoload_entries=[{"path": str(skill), "filename": "s.md"}],
        placeholders=ctx,
    )
    assert "{{ SCRATCHPAD_PATH }}" not in prompt
    assert prompt.count("/scratch/abc") == 2  # body + skill


def test_environment_info_lists_scratchpad() -> None:
    info = format_environment_info(current_cwd="/p", scratchpad_dir="/s/1")
    assert "Session Scratchpad: /s/1" in info
    assert "Workspace" not in info


# ---------------------------------------------------------------------------
# Approval: scratchpad behaves like the CWD in every mode
# ---------------------------------------------------------------------------


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    if approval._find_enclosing_git_root(str(tmp_path)) is not None:
        pytest.skip("pytest tmp_path is itself inside a git repository")
    cwd = tmp_path / "project"
    scratch = tmp_path / "scratch"
    cwd.mkdir()
    scratch.mkdir()
    (scratch / "notes.txt").write_text("x", encoding="utf-8")
    return cwd, scratch


def _needs(tool: str, args: dict, cwd: Path, scratch: Path, mode: str) -> bool:
    sr = {
        "session_init_working_dir": str(cwd),
        "session_current_working_dir": str(cwd),
        "session_scratchpad_dir": str(scratch),
        "approval_mode": mode,
    }
    needs, _hop = check_needs_approval(
        tool, args, special_resources=sr, session_data={"memory": {}}
    )
    return needs


def test_scratchpad_writes_follow_cwd_semantics(roots) -> None:
    cwd, scratch = roots
    args = {"path": str(scratch / "new.txt"), "content": "x"}
    assert _needs("write_text_file", args, cwd, scratch, "default")
    assert not _needs("write_text_file", args, cwd, scratch, "auto-accept-edits")


def test_scratchpad_reads_are_auto_approved(roots) -> None:
    cwd, scratch = roots
    assert not _needs(
        "read_text_file", {"path": str(scratch / "notes.txt")}, cwd, scratch, "default"
    )
    assert not _needs("list_dir", {"path": str(scratch)}, cwd, scratch, "default")


def test_other_paths_outside_roots_still_ask(roots, tmp_path: Path) -> None:
    cwd, scratch = roots
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x", encoding="utf-8")
    assert _needs("read_text_file", {"path": str(outside)}, cwd, scratch, "default")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_new_id_route_issues_id_and_workspace(fake_home: Path) -> None:
    data = app.test_client().get("/api/sessions/new-id").get_json()
    assert session_dirs.is_valid_session_id(data["session_id"])
    assert data["workspace_dir"] == session_dirs.get_session_workspace_dir(
        data["session_id"]
    )
    # Issuing an id creates nothing on disk.
    assert not Path(data["workspace_dir"]).exists()


def test_create_rejects_malformed_session_id() -> None:
    response = app.test_client().post(
        "/api/sessions", json={"session_id": "../x", "initial_cwd": "/tmp"}
    )
    assert response.status_code == 400


def test_create_rejects_existing_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_api, "load_session_meta", lambda _sid: {"session_id": _sid}
    )
    response = app.test_client().post(
        "/api/sessions",
        json={"session_id": str(uuid.uuid4()), "initial_cwd": "/tmp"},
    )
    assert response.status_code == 409
