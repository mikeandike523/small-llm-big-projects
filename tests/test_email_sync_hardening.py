"""Gmail history sync hardening: 404 skips, cursor recovery, lease, monotonic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.channels.email.message_ingest as ingest_module
import src.channels.email.recovery as recovery_module
import src.channels.email.state as state_module
import src.channels.email.sync as sync_module
from src.channels.email.config import EmailConfig
from src.channels.email.state import GmailMailboxState

NOW = 1_800_000_000.0
DAY = 24 * 60 * 60


class NotFound(Exception):
    status_code = 404


class ServerError(Exception):
    status_code = 500


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeGmail:
    """Chained googleapiclient-style fake. Values may be dicts or exceptions."""

    def __init__(self, *, history, messages, threads, profile=None, listing=None):
        self.history_pages = list(history)
        self.messages_by_id = messages
        self.threads_by_id = threads
        self.profile = profile
        self.listing_pages = list(listing or [])
        self.calls: list[tuple] = []

    def users(self):
        return self

    def history(self):
        return SimpleNamespace(list=self._history_list)

    def messages(self):
        return SimpleNamespace(get=self._message_get, list=self._message_list)

    def threads(self):
        return SimpleNamespace(get=self._thread_get)

    def getProfile(self, userId):
        self.calls.append(("getProfile",))
        return _Call(lambda: self.profile)

    @staticmethod
    def _result(value):
        if isinstance(value, Exception):
            raise value
        return value

    def _history_list(self, **kwargs):
        self.calls.append(("history.list", kwargs["startHistoryId"]))
        return _Call(lambda: self._result(self.history_pages.pop(0)))

    def _message_list(self, **kwargs):
        self.calls.append(("messages.list", kwargs["q"]))
        return _Call(lambda: self._result(self.listing_pages.pop(0)))

    def _message_get(self, *, id, **_kwargs):
        self.calls.append(("messages.get", id))
        return _Call(lambda: self._result(self.messages_by_id[id]))

    def _thread_get(self, *, id, **_kwargs):
        self.calls.append(("threads.get", id))
        return _Call(lambda: self._result(self.threads_by_id[id]))


def _config() -> EmailConfig:
    return EmailConfig(
        mailbox_email="mailbox@example.test",
        system_alias_address="system@example.test",
        system_alias_name="Example System",
        project_id="p",
        processor_service_account_email="processor@p.iam.gserviceaccount.com",
        topic_resource="projects/p/topics/t",
        subscription_resource="projects/p/subscriptions/s",
        push_service_account_email="push@p.iam.gserviceaccount.com",
        push_audience="https://agent.example.test/webhooks/gmail",
    )


def _state(cursor="100", **overrides) -> GmailMailboxState:
    values = dict(
        mailbox_email="mailbox@example.test",
        last_processed_history_id=cursor,
        initialization_started_unix=None,
        watch_last_attempt_unix=None,
        watch_last_success_unix=None,
        watch_expiration_ms=None,
        watch_next_attempt_unix=None,
        watch_last_error=None,
        sync_last_attempt_unix=None,
        sync_last_success_unix=NOW - 3 * DAY,
        sync_last_error=None,
    )
    values.update(overrides)
    return GmailMailboxState(**values)


@pytest.fixture
def db(monkeypatch):
    """In-memory replacements for every MySQL-touching helper."""
    record = SimpleNamespace(
        state=_state(),
        cursor_moves=[],
        batches_processed=[],
        sync_failures=[],
        cursor_resets=[],
        upserts=[],
        lease_held=True,
    )
    m = monkeypatch
    m.setattr(sync_module, "acquire_sync_lease", lambda *a: True)
    m.setattr(sync_module, "release_sync_lease", lambda *a: None)
    m.setattr(sync_module, "load_mailbox_state", lambda _m: record.state)
    m.setattr(sync_module, "record_sync_attempt", lambda *a: None)
    m.setattr(sync_module, "claim_pending_batch", lambda *a: None)
    m.setattr(sync_module, "record_sync_success", lambda *a: None)
    m.setattr(sync_module, "record_batch_error", lambda *a: None)
    m.setattr(
        sync_module, "record_sync_failure", lambda *a: record.sync_failures.append(a)
    )
    m.setattr(
        sync_module,
        "mark_batch_processed",
        lambda *a: record.batches_processed.append(a),
    )

    def advance(_mailbox, expected, next_value):
        record.cursor_moves.append((expected, next_value))

    m.setattr(sync_module, "advance_cursor", advance)
    m.setattr(recovery_module, "advance_cursor", advance)
    m.setattr(
        recovery_module,
        "record_cursor_reset",
        lambda _m, _now, detail: record.cursor_resets.append(detail),
    )
    m.setattr(ingest_module, "renew_sync_lease", lambda *a: record.lease_held)
    m.setattr(ingest_module, "is_debug_thread_known", lambda _t: False)
    m.setattr(ingest_module, "upsert_debug_message", record.upserts.append)
    m.setattr(ingest_module, "route_inbound_message", lambda *_a, **_k: [])
    m.setattr(
        ingest_module, "list_registered_emails", lambda: {"assistant@example.test"}
    )
    m.setattr(ingest_module, "list_all_claimed_aliases", set)
    m.setattr(
        ingest_module,
        "parse_gmail_message",
        lambda raw: SimpleNamespace(id=raw["id"], gmail_thread_id=raw["threadId"]),
    )
    m.setattr(
        ingest_module,
        "classify_alias_message",
        lambda parsed, _alias: SimpleNamespace(
            id=parsed.id,
            gmail_thread_id=parsed.gmail_thread_id,
            relevant_to_alias=True,
        ),
    )
    return record


def _msg(message_id: str, thread_id: str = "t1") -> dict:
    return {"id": message_id, "threadId": thread_id}


def _history(*message_ids: str, history_id: str = "200") -> dict:
    return {
        "historyId": history_id,
        "history": [
            {"messagesAdded": [{"message": {"id": mid}} for mid in message_ids]}
        ],
    }


def test_deleted_message_is_skipped_and_cursor_still_advances(db) -> None:
    gmail = FakeGmail(
        history=[_history("gone", "m2")],
        messages={"gone": NotFound("deleted"), "m2": _msg("m2")},
        threads={"t1": {"messages": [_msg("m2")]}},
    )
    assert sync_module.synchronize_mailbox(gmail, _config(), now=NOW) is True
    assert db.cursor_moves == [("100", "200")]
    assert len(db.batches_processed) == 1
    assert [u.id for u in db.upserts] == ["m2"]


def test_deleted_thread_is_skipped(db) -> None:
    gmail = FakeGmail(
        history=[_history("m1")],
        messages={"m1": _msg("m1")},
        threads={"t1": NotFound("thread deleted")},
    )
    assert sync_module.synchronize_mailbox(gmail, _config(), now=NOW) is True
    assert db.cursor_moves == [("100", "200")]


def test_other_errors_still_fail_and_preserve_cursor(db) -> None:
    gmail = FakeGmail(
        history=[_history("m1")],
        messages={"m1": ServerError("boom")},
        threads={},
    )
    with pytest.raises(ServerError):
        sync_module.synchronize_mailbox(gmail, _config(), now=NOW)
    assert db.cursor_moves == []
    assert db.batches_processed == []
    assert len(db.sync_failures) == 1


def test_expired_cursor_recovers_with_profile_taken_before_gap_scan(db) -> None:
    gmail = FakeGmail(
        history=[NotFound("Requested entity was not found.")],
        messages={"g1": _msg("g1"), "g2": _msg("g2", "t2")},
        threads={
            "t1": {"messages": [_msg("g1")]},
            "t2": {"messages": [_msg("g2", "t2")]},
        },
        profile={"historyId": "900"},
        listing=[
            {"messages": [{"id": "g1"}], "nextPageToken": "p2"},
            {"messages": [{"id": "g2"}]},
        ],
    )
    assert sync_module.synchronize_mailbox(gmail, _config(), now=NOW) is True

    names = [call[0] for call in gmail.calls]
    assert names.index("getProfile") < names.index("messages.list")
    expected_after = int(NOW - 3 * DAY - DAY)
    assert ("messages.list", f"after:{expected_after}") in gmail.calls
    assert db.cursor_moves == [("100", "900")]
    assert {u.id for u in db.upserts} == {"g1", "g2"}
    assert len(db.batches_processed) == 1
    (detail,) = db.cursor_resets
    assert detail["messages_scanned"] == 2
    assert detail["capped"] is False


def test_gap_scan_cap_is_recorded(db, monkeypatch) -> None:
    monkeypatch.setattr(recovery_module, "MAX_GAP_MESSAGES", 1)
    gmail = FakeGmail(
        history=[NotFound("expired")],
        messages={"g1": _msg("g1")},
        threads={"t1": {"messages": [_msg("g1")]}},
        profile={"historyId": "900"},
        listing=[{"messages": [{"id": "g1"}, {"id": "g2"}]}],
    )
    run = ingest_module.IngestRun(gmail, _config(), "owner")
    detail = recovery_module.recover_expired_cursor(
        gmail, _config(), db.state, "100", run, NOW, max_messages=1
    )
    assert detail["capped"] is True
    assert detail["messages_scanned"] == 1
    assert db.cursor_moves == [("100", "900")]


def test_recovery_window_math() -> None:
    window = recovery_module.recovery_window_start
    assert window(_state(sync_last_success_unix=NOW - DAY), NOW) == NOW - 2 * DAY
    assert window(_state(sync_last_success_unix=NOW - 90 * DAY), NOW) == (
        NOW - 30 * DAY
    )
    fallback = _state(sync_last_success_unix=None, watch_last_success_unix=NOW - DAY)
    assert window(fallback, NOW) == NOW - 2 * DAY
    nothing = _state(sync_last_success_unix=None)
    assert window(nothing, NOW) == NOW - 7 * DAY


def test_lost_lease_abandons_sync_without_advancing(db) -> None:
    db.lease_held = False
    gmail = FakeGmail(
        history=[{**_history("m1"), "nextPageToken": "p2"}, _history("m2")],
        messages={"m1": _msg("m1"), "m2": _msg("m2")},
        threads={"t1": {"messages": []}},
    )
    assert sync_module.synchronize_mailbox(gmail, _config(), now=NOW) is False
    assert db.cursor_moves == []
    assert db.batches_processed == []
    assert db.sync_failures == []


def test_advance_cursor_refuses_to_move_backwards(monkeypatch) -> None:
    def no_db():
        raise AssertionError("must reject before touching the database")

    monkeypatch.setattr(state_module, "get_pool", no_db)
    with pytest.raises(RuntimeError, match="backwards"):
        # "99" > "100" as strings; numeric comparison must still reject it.
        state_module.advance_cursor("mailbox@example.test", "100", "99")


def test_sync_holds_new_turns_until_it_ends_even_when_it_fails(db, monkeypatch) -> None:
    import src.channels.email.email_runner as runner_module

    woken: list[bool] = []
    monkeypatch.setattr(runner_module, "notify_email_runner", lambda: woken.append(True))
    held_during_fetch: list[bool] = []

    def fail_during_sync(*_a):
        held_during_fetch.append(runner_module.intake_in_progress())
        raise ServerError("backend error")

    monkeypatch.setattr(sync_module, "_sync_history", fail_during_sync)
    with pytest.raises(ServerError):
        sync_module.synchronize_mailbox(
            FakeGmail(history=[], messages={}, threads={}), _config(), now=NOW
        )
    assert held_during_fetch == [True]
    assert not runner_module.intake_in_progress()
    assert woken == [True]
