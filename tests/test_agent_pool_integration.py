"""Pool sessions: settings from the agent, backend guards, routes, prompt,
pending approvals and delete behavior."""

from __future__ import annotations

import pytest

# Import the app first: importing emit-dependent modules in isolation hits a
# pre-existing emit <-> session_store circular import.
from src.ui_connector.app import app  # noqa: I001

import src.ui_connector.socket_handler_components.agents_api as api
import src.utils.agent_store as agent_store
from src.ui_connector.socket_handler_components import runtime_settings
from src.utils.session_model import Session
from src.utils.sql.agents_db import Agent


def _agent(**overrides) -> Agent:
    values = dict(
        id="agent-1",
        slug="helper",
        name="Helper",
        email="agent@example.test",
        registered_at=1.0,
        enabled=True,
        allowed_senders=("person@example.test",),
        profile_name="agent-profile",
        approval_mode="full-auto",
        automation_approval_policy="force-fail",
        created_at=1.0,
    )
    values.update(overrides)
    return Agent(**values)


# -- settings come from the agent ---------------------------------------------


def test_agent_settings_replace_the_sessions_own_on_every_read(monkeypatch) -> None:
    current = {"agent": _agent()}
    monkeypatch.setattr(runtime_settings, "get_agent", lambda _id: current["agent"])
    session_id = "agent-settings-overlay"
    session = Session(
        session_id=session_id,
        agent_id="agent-1",
        profile_name="own-profile",
        approval_mode="default",
    )
    try:
        first = runtime_settings.snapshot(session_id, session)
        assert first.profile_name == "agent-profile"
        assert first.approval_mode == "full-auto"
        # A change is visible at the next read, as for a normal session's settings.
        current["agent"] = _agent(profile_name="new", approval_mode="default")
        second = runtime_settings.snapshot(session_id, session)
        assert (second.profile_name, second.approval_mode) == ("new", "default")
        assert runtime_settings.peek(session_id).profile_name == "new"
        runtime_settings.merge_into_session(session_id, session)
        assert session.profile_name == "new"
    finally:
        runtime_settings.discard(session_id)


def test_normal_session_settings_are_untouched(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_settings,
        "get_agent",
        lambda _id: pytest.fail("a normal session has no agent"),
    )
    session_id = "agent-settings-normal"
    session = Session(session_id=session_id, profile_name="own-profile")
    try:
        assert runtime_settings.snapshot(session_id, session).profile_name == (
            "own-profile"
        )
    finally:
        runtime_settings.discard(session_id)


# -- backend guards -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("patch", "profile", {"profile_name": ""}),
        ("patch", "approval-mode", {"approval_mode": "default"}),
        (
            "patch",
            "heartbeat-settings",
            {
                "enabled": True,
                "interval_minutes": 30,
                "instructions": "x",
                "heartbeat_approval_policy": "wait-for-human",
                "followup_behavior": "auto",
            },
        ),
        ("post", "reload-custom-skills-tools", None),
    ],
)
def test_pool_session_settings_cannot_be_changed(
    monkeypatch, method, path, body
) -> None:
    import src.ui_connector.socket_handler_components.http_api as http_api

    monkeypatch.setattr(
        http_api,
        "_load_session_info",
        lambda sid: Session(session_id=sid, agent_id="agent-1"),
    )
    client = app.test_client()
    response = getattr(client, method)(f"/api/sessions/s1/{path}", json=body)
    assert response.status_code == 409
    assert "managed by its agent" in response.get_json()["error"]


def test_session_list_leaves_out_pool_sessions(monkeypatch) -> None:
    import src.ui_connector.socket_handler_components.http_api as http_api

    monkeypatch.setattr(
        http_api,
        "list_session_meta",
        lambda: [
            {"session_id": "normal", "agent_id": None},
            {"session_id": "pooled", "agent_id": "agent-1"},
        ],
    )
    rows = app.test_client().get("/api/sessions").get_json()
    assert [row["session_id"] for row in rows] == ["normal"]


def test_heartbeat_daemon_skips_pool_sessions(monkeypatch) -> None:
    import src.ui_connector.heartbeat_daemon as daemon

    monkeypatch.setattr(
        daemon,
        "list_session_meta",
        lambda: [
            {"session_id": "pooled", "heartbeat_enabled": True, "agent_id": "a1"},
        ],
    )
    monkeypatch.setattr(
        daemon,
        "_heartbeat_settings_for",
        lambda _sid: pytest.fail("a pool session is never considered"),
    )
    assert daemon._load_enabled_sessions() == []


# -- agent routes -------------------------------------------------------------


@pytest.fixture
def agents_env(monkeypatch):
    state = {
        "agents": {},
        "discarded": [],
        "running": False,
        "deleted": [],
        "unretire_conflict": False,
    }

    def create(identity, settings):
        if any(a.email == identity.email for a in state["agents"].values()):
            raise agent_store.AgentConflictError("taken", field="email")
        agent = _agent(name=identity.name, email=identity.email)
        state["agents"][agent.id] = agent
        return agent

    monkeypatch.setattr(api, "_check_profile_exists", lambda _name: None)
    monkeypatch.setattr(agent_store, "create_agent", create)
    monkeypatch.setattr(agent_store, "get_agent", state["agents"].get)
    monkeypatch.setattr(
        agent_store,
        "retire",
        lambda aid: state["agents"].update({aid: _agent(retired_at=5.0)}),
    )

    def unretire(aid):
        if state["unretire_conflict"]:
            raise agent_store.AgentConflictError("taken", field="email")
        state["agents"][aid] = _agent()

    monkeypatch.setattr(agent_store, "unretire", unretire)
    monkeypatch.setattr(agent_store, "delete", lambda aid: state["agents"].pop(aid))
    monkeypatch.setattr(api, "_discard_queued", state["discarded"].append)
    monkeypatch.setattr(api, "_notify_runner", lambda: None)
    monkeypatch.setattr(api, "_has_running_turn", lambda _aid: state["running"])
    monkeypatch.setattr(api.agents_db, "agent_session_ids", lambda _aid: ["s1", "s2"])
    monkeypatch.setattr(api, "_delete_sessions", state["deleted"].extend)
    monkeypatch.setattr(
        api.agents_db, "list_agents", lambda: list(state["agents"].values())
    )
    monkeypatch.setattr(api.agents_db, "list_pool_rows", lambda: [])
    return state, app.test_client()


def _agent_body(**overrides) -> dict:
    return {
        "name": "Helper",
        "email": "Agent@Example.test",
        "enabled": True,
        "allowed_senders": "person@example.test",
        "profile_name": "agent-profile",
        "approval_mode": "default",
        "automation_approval_policy": "wait-for-human",
        **overrides,
    }


def test_create_agent_lowercases_the_email(agents_env) -> None:
    _state, client = agents_env
    response = client.post("/api/agents", json=_agent_body())
    assert response.status_code == 201
    assert response.get_json()["email"] == "agent@example.test"


def test_conflicting_agent_is_409_with_field(agents_env) -> None:
    _state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    response = client.post("/api/agents", json=_agent_body(name="Other"))
    assert response.status_code == 409
    assert response.get_json()["field"] == "email"


def test_invalid_sender_line_is_400_with_field(agents_env) -> None:
    _state, client = agents_env
    response = client.post(
        "/api/agents", json=_agent_body(allowed_senders="ok@example.test\nbad")
    )
    assert response.status_code == 400
    assert response.get_json()["field"] == "allowed_senders"


def test_retire_is_refused_while_a_turn_runs(agents_env) -> None:
    state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    state["running"] = True
    response = client.post("/api/agents/agent-1/retire")
    assert response.status_code == 409
    assert not state["agents"]["agent-1"].is_retired


def test_retire_discards_queued_mail_and_keeps_the_identity(agents_env) -> None:
    state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    assert client.post("/api/agents/agent-1/retire").status_code == 200
    assert state["discarded"] == ["agent-1"]
    retired = client.get("/api/agents").get_json()[0]
    assert retired["retired_at"] == 5.0
    assert retired["email"] == "agent@example.test"


def test_unretire_reactivates_or_reports_the_conflict(agents_env) -> None:
    state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    client.post("/api/agents/agent-1/retire")
    state["unretire_conflict"] = True
    response = client.post("/api/agents/agent-1/unretire")
    assert response.status_code == 409
    assert response.get_json()["field"] == "email"
    state["unretire_conflict"] = False
    assert client.post("/api/agents/agent-1/unretire").status_code == 200
    assert not state["agents"]["agent-1"].is_retired


def test_delete_is_refused_while_a_turn_runs(agents_env) -> None:
    state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    state["running"] = True
    assert client.delete("/api/agents/agent-1").status_code == 409
    assert state["deleted"] == []
    assert state["discarded"] == []


def test_deleting_an_active_agent_retires_it_first(agents_env, monkeypatch) -> None:
    state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    retired: list = []
    original = agent_store.retire
    monkeypatch.setattr(
        agent_store, "retire", lambda aid: (retired.append(aid), original(aid))
    )
    assert client.delete("/api/agents/agent-1").status_code == 200
    assert retired == ["agent-1"]
    assert state["discarded"] == ["agent-1"]
    assert state["deleted"] == ["s1", "s2"]


def test_deleting_a_retired_agent_removes_sessions(agents_env) -> None:
    state, client = agents_env
    client.post("/api/agents", json=_agent_body())
    client.post("/api/agents/agent-1/retire")
    assert client.delete("/api/agents/agent-1").status_code == 200
    assert state["deleted"] == ["s1", "s2"]
    assert "agent-1" not in state["agents"]


# -- system prompt section ---------------------------------------------------


def test_prompt_section_only_for_pool_sessions(monkeypatch, tmp_path) -> None:
    import src.logic.agent_prompt as prompt

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("Dry humor.", encoding="utf-8")
    monkeypatch.setattr(prompt, "get_agent", lambda _id: _agent())
    monkeypatch.setattr(prompt, "get_agent_workspace", lambda _slug: str(workspace))
    monkeypatch.setattr(prompt, "conversation_sender", lambda _sid: "ana@example.test")

    assert prompt.build_agent_prompt_section(Session(session_id="plain")) is None
    section = prompt.build_agent_prompt_section(
        Session(session_id="pooled", agent_id="agent-1")
    )
    assert "You are Helper" in section
    assert "conversation, with ana@example.test" in section
    assert "Dry humor." in section
    assert f"{workspace}/MEMORY.md" in section
    assert "scratchpads" in section


def test_soul_is_capped_and_a_missing_one_is_not_fatal(monkeypatch, tmp_path) -> None:
    import src.logic.agent_prompt as prompt

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(prompt, "get_agent", lambda _id: _agent())
    monkeypatch.setattr(prompt, "get_agent_workspace", lambda _slug: str(workspace))
    monkeypatch.setattr(prompt, "conversation_sender", lambda _sid: None)
    session = Session(session_id="pooled", agent_id="agent-1")

    assert "(empty so far)" in prompt.build_agent_prompt_section(session)
    (workspace / "SOUL.md").write_text("x" * 9000, encoding="utf-8")
    section = prompt.build_agent_prompt_section(session)
    assert "x" * 8000 in section and "x" * 8001 not in section
    assert "Please shorten it" in section


# -- web messages to a pool session -------------------------------------------


def test_pool_session_refuses_messages_from_the_web_ui(monkeypatch) -> None:
    from types import SimpleNamespace

    import src.ui_connector.socket_handler_components.socket_events_turn as turn_events
    from src.ui_connector.socket_handler_components import state

    errors: list[dict] = []
    monkeypatch.setitem(state._sid_to_session_id, "sid-1", "pooled")
    monkeypatch.setattr(turn_events, "request", SimpleNamespace(sid="sid-1"))
    monkeypatch.setattr(
        turn_events, "load_session_meta", lambda _sid: {"agent_id": "agent-1"}
    )
    monkeypatch.setattr(
        turn_events,
        "new_user_message",
        lambda *_a, **_k: pytest.fail("the message must not start a turn"),
    )
    monkeypatch.setattr(
        turn_events, "emit", lambda _event, payload: errors.append(payload)
    )
    turn_events.handle_user_message({"text": "hello"})
    assert errors == [{"message": "This session only takes messages by email."}]


# -- the approval a turn is waiting on ----------------------------------------


def _pending_entry() -> dict:
    return {
        "tool_id": "tool-1",
        "tool_name": "host_shell",
        "args": {"cmdline": "ls"},
        "turn_id": "t1",
        "subturn_id": "st1",
    }


def test_page_load_gets_the_pending_approval_after_the_log_expired(monkeypatch) -> None:
    from src.ui_connector.socket_handler_components import state
    from src.ui_connector.socket_handler_components.history_loader import (
        _with_pending_approval,
    )

    monkeypatch.setitem(state._pending_approvals, "s1", _pending_entry())
    events = _with_pending_approval("s1", [])
    assert [event["type"] for event in events] == ["approval_request"]
    assert events[0]["data"]["id"] == "tool-1"
    assert events[0]["data"]["tool_name"] == "host_shell"
    assert events[0]["data"]["turn_id"] == "t1"


def test_page_load_does_not_duplicate_an_approval_still_in_the_log(monkeypatch) -> None:
    from src.ui_connector.socket_handler_components import state
    from src.ui_connector.socket_handler_components.history_loader import (
        _with_pending_approval,
    )

    monkeypatch.setitem(state._pending_approvals, "s1", _pending_entry())
    logged = [{"id": "1-0", "type": "approval_request", "data": {"id": "tool-1"}}]
    assert _with_pending_approval("s1", logged) == logged
    assert _with_pending_approval("no-approval", logged) == logged


def test_starting_to_wait_for_approval_notifies_listeners(monkeypatch) -> None:
    import threading

    from src.ui_connector.socket_handler_components import approval as approval_module
    from src.ui_connector.socket_handler_components import state

    waited: list[str] = []
    monkeypatch.setattr(state, "_approval_wait_listeners", [waited.append])
    monkeypatch.setattr(approval_module, "_emit_and_log", lambda *_a: None)
    cancel = threading.Event()
    cancel.set()  # ends the wait at once
    approval_module._request_approval(
        "listener-session", "tool-1", "host_shell", {}, cancel_event=cancel
    )
    assert waited == ["listener-session"]


def test_a_failing_wait_listener_does_not_affect_the_turn(monkeypatch) -> None:
    from src.ui_connector.socket_handler_components import state

    def broken(_session_id):
        raise RuntimeError("listener failed")

    monkeypatch.setattr(state, "_approval_wait_listeners", [broken])
    state.notify_approval_wait("s1")


# -- deleting sessions --------------------------------------------------------


@pytest.fixture
def delete_env(monkeypatch):
    import src.channels.email.inbound_store as inbound_store
    import src.ui_connector.socket_handler_components.session_store as store

    state = {"param": False, "workspaces": [], "discarded": [], "meta": {}, "order": []}

    monkeypatch.setattr(
        store,
        "_standalone_workspaces_to_clear",
        store._standalone_workspaces_to_clear,
    )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class Pool:
        def get_connection(self):
            return Conn()

    monkeypatch.setattr("src.data.get_pool", lambda: Pool())
    monkeypatch.setattr(
        "src.utils.param_helper.get_param_value",
        lambda _kv, _name: state["param"],
    )
    monkeypatch.setattr(
        "src.utils.sql.kv_manager.KVManager", lambda conn: conn, raising=True
    )
    monkeypatch.setattr(store, "load_session_meta", lambda sid: state["meta"].get(sid))
    monkeypatch.setattr(
        inbound_store,
        "delete_single_session_rows",
        lambda _sid: 0,
    )
    monkeypatch.setattr(
        inbound_store,
        "discard_queued_for_session",
        lambda sid: state["order"].append(f"discard {sid}"),
    )
    monkeypatch.setattr(
        store,
        "delete_sessions",
        lambda ids: state["order"].append(f"delete {ids}"),
    )
    monkeypatch.setattr(store, "delete_session_scratchpad", lambda _sid: None)
    monkeypatch.setattr(
        store,
        "delete_session_workspace",
        lambda sid: state["workspaces"].append(sid),
    )

    class Redis:
        def delete(self, *_keys):
            return 0

    monkeypatch.setattr(store._state, "_get_redis", lambda: Redis())
    return store, state


def test_deleting_keeps_workspaces_by_default(delete_env) -> None:
    store, state = delete_env
    store._delete_sessions(["s1"])
    assert state["workspaces"] == []


def test_param_clears_only_standalone_session_workspaces(delete_env) -> None:
    store, state = delete_env
    state["param"] = True
    state["meta"] = {"standalone": {"agent_id": None}, "pooled": {"agent_id": "a1"}}
    store._delete_sessions(["standalone", "pooled"])
    assert state["workspaces"] == ["standalone"]


def test_queued_mail_is_discarded_before_the_session_goes(delete_env) -> None:
    store, state = delete_env
    store._delete_sessions(["s1"])
    assert state["order"] == ["discard s1", "delete ['s1']"]


def test_clear_workspace_param_is_global_and_off_by_default() -> None:
    from src.ui_connector.socket_handler_components.session_store import (
        CLEAR_WORKSPACE_ON_DELETE_PARAM,
    )
    from src.utils.param_registry import REGISTRY

    spec = REGISTRY[CLEAR_WORKSPACE_ON_DELETE_PARAM]
    assert (spec.scope, spec.default) == ("global", False)


def test_workspace_delete_refuses_anything_but_a_session_id(
    monkeypatch, tmp_path
) -> None:
    from src.utils import session_dirs

    monkeypatch.setattr(session_dirs, "_slbp_home", lambda: tmp_path)
    session_id = "11111111-1111-4111-8111-111111111111"
    folder = tmp_path / "workspaces" / session_id
    folder.mkdir(parents=True)
    other = tmp_path / "workspaces" / "real-project"
    other.mkdir()

    session_dirs.delete_session_workspace("real-project")
    session_dirs.delete_session_workspace("../workspaces/real-project")
    assert other.exists()
    session_dirs.delete_session_workspace(session_id)
    assert not folder.exists()
