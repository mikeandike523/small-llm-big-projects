from __future__ import annotations

import pytest

import src.utils.agent_store as store
from src.utils import agent_dirs
from src.utils.agent_settings import AgentIdentity, AgentSettings
from src.utils.slugs import sender_slug_base, slug_candidates, slugify
from src.utils.sql import agents_db


class DuplicateKey(Exception):
    errno = 1062

    def __init__(self, key: str) -> None:
        super().__init__(f"Duplicate entry 'x' for key 'agents.{key}'")
        self.msg = str(self)


SETTINGS = AgentSettings(
    enabled=True,
    allowed_senders=["person@example.test"],
    profile_name="p",
    approval_mode="default",
    automation_approval_policy="wait-for-human",
)


# -- slugs -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ana Díaz", "ana-diaz"),
        ("  --Hello, World!-- ", "hello-world"),
        ("a/b\\c?d*e", "a-b-c-d-e"),
        ("../../etc/passwd", "etc-passwd"),
        ("CON", "con-x"),
        ("lpt1", "lpt1-x"),
        ("日本語", "fallback"),
        ("", "fallback"),
    ],
)
def test_slugify_is_always_folder_safe(text: str, expected: str) -> None:
    assert slugify(text, fallback="fallback") == expected


def test_slug_is_length_capped_without_a_trailing_hyphen() -> None:
    slug = slugify("a" * 47 + " b", fallback="f")
    assert len(slug) <= 48 and not slug.endswith("-")


def test_slug_candidates_count_up_from_two() -> None:
    candidates = slug_candidates("ana")
    assert [next(candidates) for _ in range(3)] == ["ana", "ana-2", "ana-3"]


@pytest.mark.parametrize(
    ("name", "address", "expected"),
    [
        ("Ana Diaz", "x@example.test", "ana-diaz"),
        (None, "Bob.Smith@example.test", "bob-smith"),
        ("日本語", "bob@example.test", "bob"),
        (None, "???@example.test", "user"),
    ],
)
def test_sender_slug_prefers_the_name_then_the_address(name, address, expected) -> None:
    assert sender_slug_base(name, address) == expected


# -- folders -----------------------------------------------------------------


def test_agent_dirs_are_created_and_existing_files_kept(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_dirs.Path, "home", lambda: tmp_path)
    workspace = tmp_path / ".slbp" / "agents" / "helper" / "workspace"

    user_dir = agent_dirs.ensure_user_dir("helper", "ana")

    assert (workspace / "users" / "ana").is_dir()
    assert user_dir.endswith(".slbp/agents/helper/workspace/users/ana")
    (workspace / "SOUL.md").write_text("kept", encoding="utf-8")
    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == ""
    agent_dirs.ensure_agent_dirs("helper")
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "kept"


# -- identity ----------------------------------------------------------------


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    state = {"inserted": [], "conflict": None, "taken_slugs": set()}

    def insert(agent, *, name_key):
        if agent.slug in state["taken_slugs"]:
            raise DuplicateKey("uq_agents_slug")
        state["inserted"].append((agent, name_key))

    monkeypatch.setattr(agents_db, "insert_agent", insert)
    monkeypatch.setattr(
        agents_db, "identity_conflict", lambda *_a, **_k: state["conflict"]
    )
    monkeypatch.setattr(store, "ensure_agent_dirs", lambda _slug: None)
    state["held_by_session"] = None
    monkeypatch.setattr(
        store, "held_by_session_message", lambda _email: state["held_by_session"]
    )
    return state


def test_create_keeps_the_name_case_and_compares_it_folded(fake_db) -> None:
    agent = store.create_agent(AgentIdentity("Ana", "a@example.test"), SETTINGS)
    assert agent.name == "Ana"
    assert agent.slug == "ana"
    assert fake_db["inserted"][0][1] == "ana"


def test_name_key_ignores_case() -> None:
    assert (
        AgentIdentity("ANA", "a@example.test").name_key
        == AgentIdentity("ana", "b@example.test").name_key
    )


def test_create_takes_the_next_free_slug(fake_db) -> None:
    fake_db["taken_slugs"] = {"ana", "ana-2"}
    agent = store.create_agent(AgentIdentity("Ana", "a@example.test"), SETTINGS)
    assert agent.slug == "ana-3"


@pytest.mark.parametrize("field", ["name", "email"])
def test_conflict_names_its_field(fake_db, field) -> None:
    fake_db["conflict"] = field
    with pytest.raises(store.AgentConflictError) as info:
        store.create_agent(AgentIdentity("Ana", "a@example.test"), SETTINGS)
    assert info.value.field == field
    assert fake_db["inserted"] == []


def test_simultaneous_claim_is_decided_by_the_unique_key(fake_db, monkeypatch) -> None:
    def insert(_agent, *, name_key):
        raise DuplicateKey("uq_agents_active_email")

    monkeypatch.setattr(agents_db, "insert_agent", insert)
    with pytest.raises(store.AgentConflictError) as info:
        store.create_agent(AgentIdentity("Ana", "a@example.test"), SETTINGS)
    assert info.value.field == "email"


def test_writes_refresh_the_cached_agent(monkeypatch) -> None:
    loads = []

    def load(agent_id):
        loads.append(agent_id)
        return object()

    monkeypatch.setattr(agents_db, "load_agent", load)
    monkeypatch.setattr(agents_db, "update_agent_settings", lambda *_a, **_k: None)
    monkeypatch.setattr(agents_db, "set_retired", lambda *_a, **_k: None)
    store.invalidate("cached")

    store.get_agent("cached")
    store.get_agent("cached")
    assert len(loads) == 1
    store.update_settings("cached", SETTINGS)
    store.get_agent("cached")
    assert len(loads) == 2
    store.retire("cached")
    store.get_agent("cached")
    assert len(loads) == 3
    store.invalidate("cached")
