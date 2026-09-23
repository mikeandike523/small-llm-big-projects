# Import the app package first: session_store.py, app.py, socket_handlers.py,
# and http_api.py form a pre-existing import cycle that only resolves cleanly
# when src.ui_connector.app is the first module in the chain to execute (it
# binds `app`/`socketio` before triggering the rest of the cycle) — see
# tests/test_llm_payload_context_retries.py's known collection issue for the
# same class of pre-existing fragility elsewhere in this cycle.
import src.ui_connector.app  # noqa: F401
import src.ui_connector.socket_handler_components.state as _state
from src.ui_connector.socket_handler_components.state import SessionToolManifest
from src.ui_connector.socket_handler_components.session_store import (
    _get_active_session_tool_defs_and_map,
    _get_session_tool_defs,
    _get_session_tool_map,
)


def _def(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def test_active_tool_set_includes_base_and_only_active_skills() -> None:
    session_id = "active-tool-set-test"
    manifest = SessionToolManifest(
        base_defs=[_def("always_here")],
        base_map={"always_here": object()},
        by_skill={
            "coding": ([_def("coding_lint")], {"coding_lint": object()}),
            "web_browsing": (
                [_def("web_browsing_scrape")],
                {"web_browsing_scrape": object()},
            ),
        },
    )
    _state._session_tool_sets[session_id] = manifest
    try:
        defs, tool_map = _get_active_session_tool_defs_and_map(session_id, {"coding"})
        names = {d["function"]["name"] for d in defs}
        assert names == {"always_here", "coding_lint"}
        assert set(tool_map.keys()) == {"always_here", "coding_lint"}

        defs_none, tool_map_none = _get_active_session_tool_defs_and_map(
            session_id, set()
        )
        assert {d["function"]["name"] for d in defs_none} == {"always_here"}
        assert set(tool_map_none.keys()) == {"always_here"}

        # The full-manifest accessors (debug panel / startup calls) see every
        # skill's tools regardless of "active" status.
        full_names = {d["function"]["name"] for d in _get_session_tool_defs(session_id)}
        assert full_names == {"always_here", "coding_lint", "web_browsing_scrape"}
        assert set(_get_session_tool_map(session_id).keys()) == full_names
    finally:
        _state._session_tool_sets.pop(session_id, None)
