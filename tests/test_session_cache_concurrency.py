"""Concurrent first loads of one session must import its custom tools once.

After a server restart, a UI reconnect, HTTP routes and the heartbeat daemon
can all call _init_session_caches for the same session at the same moment.
"""

import threading
import uuid
from pathlib import Path

# The app and handler modules have a pre-existing import cycle that requires
# app to bind first (same as test_session_customization_reload.py).
import src.ui_connector.app  # noqa: F401
import src.ui_connector.socket_handler_components.session_store as store
import src.ui_connector.socket_handler_components.state as state
from src.utils.session_model import Session

_SLOW_TOOL = """
import time

time.sleep(0.5)  # widen the window in which a second loader could collide

DEFINITION = {
    "type": "function",
    "function": {
        "name": "slow_tool",
        "description": "test tool",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


def execute(args, session_data, special_resources=None):
    return "ok"
"""


def _run_two_concurrent_inits(monkeypatch, tmp_path: Path) -> tuple[list, list, str]:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "slow_tool.py").write_text(_SLOW_TOOL, encoding="utf-8")
    session_id = uuid.uuid4().hex
    errors: list = []
    toasts: list = []

    monkeypatch.setattr(store, "_ensure_session_dirs_reported", lambda *_a: None)
    monkeypatch.setattr(store, "build_skill_registry", lambda **_k: [])
    monkeypatch.setattr(store, "build_system_prompt", lambda **_k: "prompt")
    monkeypatch.setattr(store, "_build_starting_environment_info", lambda *_a: "")
    monkeypatch.setattr(store, "_build_prompt_placeholders", lambda *_a: {})
    monkeypatch.setattr(store, "_emit_backend_log", lambda _sid, *c: errors.append(c))
    monkeypatch.setattr(
        store, "_emit_and_log", lambda _sid, _ev, data: toasts.append(data["message"])
    )

    barrier = threading.Barrier(2)

    def worker() -> None:
        session = Session(
            session_id=session_id,
            initial_cwd=str(tmp_path),
            load_custom_skills_tools=True,
        )
        barrier.wait()
        store._init_session_caches(session, session_id)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return errors, toasts, session_id


def _forget(session_id: str) -> None:
    for cache in (
        state._session_tool_sets,
        state._session_system_prompts,
        state._session_skill_registries,
        state._session_project_config,
        state._session_current_cwd,
    ):
        cache.pop(session_id, None)
    state.forget_session_cache_lock(session_id)


def test_concurrent_first_loads_import_custom_tools_once(monkeypatch, tmp_path):
    errors, toasts, session_id = _run_two_concurrent_inits(monkeypatch, tmp_path)
    try:
        assert errors == []
        assert toasts == []
        assert "slow_tool" in state._session_tool_sets[session_id].base_map
    finally:
        _forget(session_id)


def test_without_the_lock_the_race_reproduces(monkeypatch, tmp_path):
    """Control: proves the test above really exercises the race."""
    monkeypatch.setattr(state, "session_cache_lock", lambda _sid: threading.Lock())
    errors, toasts, session_id = _run_two_concurrent_inits(monkeypatch, tmp_path)
    try:
        assert toasts == [store.CUSTOM_TOOL_LOAD_ERROR_TOAST]
        assert "already in sys.modules" in str(errors)
    finally:
        _forget(session_id)
