"""Always-allowed files, the advisory lock and the read/write version check.

These run the real tools through execute_tool and check_needs_approval.
"""

from __future__ import annotations

import os
import threading

import pytest

from src.tools import check_needs_approval, execute_tool
from src.tools._agent_file_guard import (
    _acquire,
    _norm,
    clear_session,
    make_scope,
)


class Env:
    def __init__(self, tmp_path, session_id: str) -> None:
        self.workspace = tmp_path / "workspace"
        self.user_dir = self.workspace / "users" / "ana"
        self.user_dir.mkdir(parents=True)
        self.memory = self.workspace / "MEMORY.md"
        self.soul = self.workspace / "SOUL.md"
        self.memory.write_text("original", encoding="utf-8")
        self.soul.write_text("soul", encoding="utf-8")
        self.session_id = session_id
        self.session_data: dict = {"memory": {}}

    def resources(self, session_id: str | None = None, **extra) -> dict:
        return {
            "agent_file_scope": make_scope(str(self.workspace), str(self.user_dir)),
            "session_id": session_id or self.session_id,
            "session_current_working_dir": str(self.user_dir),
            "session_init_working_dir": str(self.user_dir),
            "session_scratchpad_dir": str(self.workspace.parent / "scratchpad"),
            **extra,
        }

    def run(self, tool: str, session_id: str | None = None, **args) -> str:
        result, _ = execute_tool(
            tool, args, self.session_data, self.resources(session_id)
        )
        return result


@pytest.fixture
def env(tmp_path):
    environment = Env(tmp_path, "session-a")
    yield environment
    clear_session("session-a")
    clear_session("session-b")


# -- your MEMORY_FILE_VALUE scenario ------------------------------------------


def test_reading_to_memory_only_covers_writes_from_that_key(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", path=path)
    env.memory.write_text("changed by another agent", encoding="utf-8")

    env.run("read_text_file", path=path, session_memory_key="MEMORY_FILE_VALUE")

    refused = env.run("write_text_file", path=path, content="from my stale context")
    assert refused.startswith("Error:") and "changed since you last read" in refused
    assert env.memory.read_text(encoding="utf-8") == "changed by another agent"

    written = env.run(
        "write_text_file", path=path, session_memory_key="MEMORY_FILE_VALUE"
    )
    assert written.startswith("File written")


def test_reading_to_context_does_not_cover_a_memory_key(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", path=path, session_memory_key="K")
    env.memory.write_text("changed", encoding="utf-8")
    env.run("read_text_file", path=path)
    refused = env.run("write_text_file", path=path, session_memory_key="K")
    assert refused.startswith("Error:") and "does not hold the current" in refused
    assert env.memory.read_text(encoding="utf-8") == "changed"


def test_one_key_does_not_cover_another(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", path=path, session_memory_key="A")
    env.session_data["memory"]["B"] = "unrelated"
    refused = env.run("write_text_file", path=path, session_memory_key="B")
    assert refused.startswith("Error:") and "'B'" in refused
    assert env.memory.read_text(encoding="utf-8") == "original"


def test_a_key_holding_another_file_cannot_overwrite_this_one(env) -> None:
    env.run("read_text_file", path=str(env.soul), session_memory_key="K")
    refused = env.run("write_text_file", path=str(env.memory), session_memory_key="K")
    assert refused.startswith("Error:")
    assert env.memory.read_text(encoding="utf-8") == "original"


# -- writes -------------------------------------------------------------------


def test_write_without_reading_is_refused(env) -> None:
    refused = env.run("write_text_file", path=str(env.memory), content="x")
    assert refused.startswith("Error:") and "read_text_file" in refused
    assert env.memory.read_text(encoding="utf-8") == "original"


def test_read_then_write_works_repeatedly(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", path=path)
    assert env.run("write_text_file", path=path, content="one").startswith("File")
    # The agent wrote this text, so it still knows the file.
    assert env.run("write_text_file", path=path, content="two").startswith("File")
    assert env.memory.read_text(encoding="utf-8") == "two"


def test_write_from_key_leaves_the_context_version_stale(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", path=path)
    env.run("read_text_file", path=path, session_memory_key="K")
    env.session_data["memory"]["K"] = "new text from memory"
    assert env.run("write_text_file", path=path, session_memory_key="K").startswith(
        "File"
    )
    # The new text was never in the agent's context.
    assert env.run("write_text_file", path=path, content="x").startswith("Error:")


def test_new_file_needs_no_read(env) -> None:
    target = env.user_dir / "notes.md"
    assert env.run("write_text_file", path=str(target), content="hi").startswith("File")
    assert env.run("create_text_file", path=str(env.user_dir / "b.md"), content="hi")
    assert target.read_text(encoding="utf-8") == "hi"


def test_two_sessions_each_need_their_own_read(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", "session-a", path=path)
    env.run("read_text_file", "session-b", path=path)
    assert env.run("write_text_file", "session-a", path=path, content="a").startswith(
        "File"
    )
    refused = env.run("write_text_file", "session-b", path=path, content="b")
    assert refused.startswith("Error:")
    assert env.memory.read_text(encoding="utf-8") == "a"
    env.run("read_text_file", "session-b", path=path)
    assert env.run("write_text_file", "session-b", path=path, content="b").startswith(
        "File"
    )


def test_partial_read_does_not_count(env) -> None:
    path = str(env.memory)
    env.run("line_reader", action="read_lines", path=path, start_line=1, end_line=1)
    assert env.run("write_text_file", path=path, content="x").startswith("Error:")


def test_failed_read_records_nothing(env) -> None:
    path = str(env.workspace / "missing.md")
    assert env.run("read_text_file", path=path).startswith("Error")
    (env.workspace / "missing.md").write_text("appeared", encoding="utf-8")
    assert env.run("write_text_file", path=path, content="x").startswith("Error:")


def test_delete_needs_a_current_read(env) -> None:
    refused = env.run("delete_file", path=str(env.memory))
    assert refused.startswith("Error:") and env.memory.exists()
    env.run("read_text_file", path=str(env.memory))
    env.run("delete_file", path=str(env.memory))
    assert not env.memory.exists()


def test_move_and_copy_over_a_guarded_file_need_a_current_read(env) -> None:
    source = env.user_dir / "source.md"
    source.write_text("source", encoding="utf-8")
    assert env.run("copy_file", src=str(source), dst=str(env.memory)).startswith(
        "Error:"
    )
    assert env.run("move_dir_or_file", src=str(source), dst=str(env.memory)).startswith(
        "Error:"
    )
    assert env.memory.read_text(encoding="utf-8") == "original" and source.exists()


def test_files_outside_the_workspace_are_not_guarded(env, tmp_path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    assert env.run("write_text_file", path=str(outside), content="y").startswith("File")


def test_sessions_without_a_scope_are_not_guarded(env) -> None:
    result, _ = execute_tool(
        "write_text_file",
        {"path": str(env.memory), "content": "y"},
        env.session_data,
        {"session_current_working_dir": str(env.user_dir)},
    )
    assert result.startswith("File written")


# -- advisory lock ------------------------------------------------------------


def test_locked_file_refuses_a_write_with_the_agreed_message(env) -> None:
    path = str(env.memory)
    env.run("read_text_file", path=path)
    held = _acquire([_norm(path)])
    try:
        refused = env.run("write_text_file", path=path, content="x")
    finally:
        for lock in held:
            lock.release()
    assert refused.startswith(
        "Error: File is under advisory lock, please wait and try again"
    )
    assert "sleep" in refused
    assert env.memory.read_text(encoding="utf-8") == "original"
    assert env.run("write_text_file", path=path, content="x").startswith("File")


def test_acquire_takes_all_locks_or_none() -> None:
    first = os.path.abspath("guard-test-a")
    second = os.path.abspath("guard-test-b")
    held_second = _acquire([second])
    assert _acquire([first, second]) == []
    # The first lock was given back when the second could not be taken.
    held_first = _acquire([first])
    assert held_first
    for lock in held_first + held_second:
        lock.release()


def test_parallel_writers_cannot_lose_an_update(env) -> None:
    """Only one of the writers that read the same version may succeed."""
    path = str(env.memory)
    sessions = [f"parallel-{i}" for i in range(8)]
    for session_id in sessions:
        env.run("read_text_file", session_id, path=path)
    barrier = threading.Barrier(len(sessions))
    results: dict[str, str] = {}

    def write(session_id: str) -> None:
        barrier.wait()
        results[session_id] = env.run(
            "write_text_file", session_id, path=path, content=session_id
        )

    threads = [threading.Thread(target=write, args=(s,)) for s in sessions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for session_id in sessions:
        clear_session(session_id)

    winners = [s for s, result in results.items() if result.startswith("File")]
    assert len(winners) == 1
    assert env.memory.read_text(encoding="utf-8") == winners[0]


# -- always allowed -----------------------------------------------------------


def _needs(env, tool, mode, **args) -> bool:
    needs, _ = check_needs_approval(
        tool, args, session_data={}, special_resources=env.resources(approval_mode=mode)
    )
    return needs


@pytest.mark.parametrize("mode", ["default", "auto-accept-edits"])
@pytest.mark.parametrize("name", ["SOUL.md", "MEMORY.md"])
def test_agents_own_files_never_ask(env, mode, name) -> None:
    path = str(env.workspace / name)
    assert not _needs(env, "write_text_file", mode, path=path, content="x")
    assert not _needs(env, "read_text_file", mode, path=path)
    assert not _needs(
        env, "text_editor", mode, action="normalize_eol", filepath=path, eol="lf"
    )


def test_current_senders_memory_never_asks(env) -> None:
    path = str(env.user_dir / "MEMORY.md")
    assert not _needs(env, "write_text_file", "default", path=path, content="x")
    # A relative path from the starting folder works too.
    assert not _needs(env, "write_text_file", "default", path="MEMORY.md", content="x")


def test_other_files_still_ask_in_default_mode(env) -> None:
    other_user = env.workspace / "users" / "bob" / "MEMORY.md"
    assert _needs(env, "write_text_file", "default", path=str(other_user), content="x")
    assert _needs(
        env, "write_text_file", "default", path=str(env.user_dir / "x.md"), content="x"
    )


def test_only_the_file_tools_are_exempt(env) -> None:
    assert _needs(env, "delete_file", "default", path=str(env.memory))
    assert _needs(env, "host_shell", "default", cmdline=f"rm {env.memory}")


def test_request_unredacted_still_asks(env) -> None:
    assert _needs(
        env, "read_text_file", "default", path=str(env.memory), request_unredacted=True
    )


def test_symlink_named_memory_is_not_allowed(env, tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    link = env.user_dir / "MEMORY.md"
    try:
        os.symlink(secret, link)
    except OSError:
        pytest.skip("this system cannot create symlinks")
    assert _needs(env, "write_text_file", "default", path=str(link), content="x")


def test_traversal_to_another_file_is_not_allowed(env) -> None:
    sneaky = str(env.workspace / "users" / ".." / ".." / "elsewhere" / "MEMORY.md")
    assert _needs(env, "write_text_file", "default", path=sneaky, content="x")


def test_sessions_without_a_scope_are_not_exempt(env) -> None:
    needs, _ = check_needs_approval(
        "write_text_file",
        {"path": str(env.memory), "content": "x"},
        session_data={},
        special_resources={
            "approval_mode": "default",
            "session_current_working_dir": str(env.user_dir),
        },
    )
    assert needs
