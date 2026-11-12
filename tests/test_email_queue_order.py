"""Queues drain by sent date, and no turn starts while a sync delivers a batch."""

from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime, timezone

import pytest

import src.channels.email.email_runner as runner_module
import src.channels.email.inbound_store as store
import src.channels.email.router as router
from test_email_runner import Harness

ACCEPTED = 1_800_000_000.0
HOUR = 60 * 60


def _date(timestamp: float) -> str:
    return format_datetime(datetime.fromtimestamp(timestamp, tz=timezone.utc))


# -- which time is used ------------------------------------------------------


def test_sent_date_is_used_when_it_is_believable() -> None:
    assert router.email_sent_time(_date(ACCEPTED - 60), ACCEPTED) == ACCEPTED - 60


@pytest.mark.parametrize("header", ["", "not a date", "Mon, 99 Foo 2026 10:00:00"])
def test_unusable_date_uses_the_accepted_time(header: str) -> None:
    assert router.email_sent_time(header, ACCEPTED) == ACCEPTED


def test_date_without_a_time_zone_is_read_as_utc() -> None:
    header = "Fri, 15 Jan 2027 08:00:00 -0000"
    expected = datetime(2027, 1, 15, 8, tzinfo=timezone.utc).timestamp()
    assert router.email_sent_time(header, expected + 5) == expected


def test_date_in_another_time_zone_is_compared_as_the_same_moment() -> None:
    header = "Fri, 15 Jan 2027 03:00:00 -0500"
    expected = datetime(2027, 1, 15, 8, tzinfo=timezone.utc).timestamp()
    assert router.email_sent_time(header, expected + 5) == expected


def test_date_after_gmail_accepted_it_is_capped() -> None:
    assert router.email_sent_time(_date(ACCEPTED + HOUR), ACCEPTED) == ACCEPTED


def test_date_more_than_a_day_early_uses_the_accepted_time() -> None:
    day = 24 * HOUR
    assert router.email_sent_time(_date(ACCEPTED - day - 1), ACCEPTED) == ACCEPTED
    assert router.email_sent_time(_date(ACCEPTED - day), ACCEPTED) == ACCEPTED - day


# -- the query really sorts that way -----------------------------------------


class _Cursor:
    def __init__(self, sql_seen: list[str]) -> None:
        self._sql_seen = sql_seen

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, _params=None):
        self._sql_seen.append(sql)

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, sql_seen: list[str]) -> None:
        self._sql_seen = sql_seen

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self, **_kwargs):
        return _Cursor(self._sql_seen)


@pytest.mark.parametrize(
    "read",
    [lambda: store.oldest_queued("s1"), store.queued_without_session],
    ids=["oldest_queued", "queued_without_session"],
)
def test_queue_reads_order_by_sent_date(monkeypatch, read) -> None:
    sql_seen: list[str] = []

    class Pool:
        def get_connection(self):
            return _Connection(sql_seen)

    monkeypatch.setattr(store, "get_pool", Pool)
    read()
    assert "ORDER BY sent_at ASC, received_at ASC, id ASC" in sql_seen[0]


# -- the runner follows that order -------------------------------------------


def test_earlier_sent_mail_runs_first_though_it_was_queued_later(monkeypatch) -> None:
    h = Harness(monkeypatch)
    later = h.store.add(sent_at=200.0, body_text="later")
    earlier = h.store.add(sent_at=100.0, body_text="earlier")
    h.runner.run_pass()
    assert h.store.rows[earlier.id].status == store.STATUS_RUNNING
    assert h.store.rows[later.id].status == store.STATUS_QUEUED
    assert h.launches[0][1].endswith("earlier")


def test_new_pool_mail_gets_its_session_in_sent_order(monkeypatch) -> None:
    h = Harness(monkeypatch)
    later = h.store.add(session_id=None, sent_at=200.0)
    earlier = h.store.add(session_id=None, sent_at=100.0)
    h.runner.run_pass()
    assert h.spawned == [earlier.id, later.id]
    assert h.store.rows[earlier.id].status == store.STATUS_RUNNING


def test_requeued_mail_goes_back_into_date_order(monkeypatch) -> None:
    h = Harness(monkeypatch, launch_results=[False, True])
    second = h.store.add(sent_at=200.0)
    first = h.store.add(sent_at=100.0)
    h.runner.run_pass()  # a human's turn got in first: back to the queue
    assert h.store.rows[first.id].status == store.STATUS_QUEUED
    h.runner.run_pass()
    assert h.store.rows[first.id].status == store.STATUS_RUNNING
    assert h.store.rows[second.id].status == store.STATUS_QUEUED


def test_an_earlier_email_arriving_late_runs_next(monkeypatch) -> None:
    from src.ui_connector.socket_handler_components.turn_outcome import TurnOutcome

    h = Harness(monkeypatch)
    running = h.store.add(sent_at=300.0)
    h.runner.run_pass()
    newest = h.store.add(sent_at=400.0)
    earliest = h.store.add(sent_at=100.0)
    h.runner.run_pass()
    assert h.store.rows[running.id].status == store.STATUS_RUNNING  # not interrupted
    h.callbacks[0](TurnOutcome(final_text="done"))
    h.runner.run_pass()
    assert h.store.rows[earliest.id].status == store.STATUS_RUNNING
    assert h.store.rows[newest.id].status == store.STATUS_QUEUED


# -- hold new turns during a sync --------------------------------------------


@pytest.fixture
def intake():
    runner_module.begin_intake()
    held = [True]

    def release() -> None:
        if held:
            held.clear()
            runner_module.end_intake()

    yield release
    release()


def test_no_turn_starts_during_a_sync_and_replies_still_go_out(
    monkeypatch, intake
) -> None:
    h = Harness(monkeypatch)
    finished = h.store.add(status=store.STATUS_DONE, final_text="answer")
    newest = h.store.add(session_id=None, sent_at=200.0)
    h.runner.run_pass()
    assert h.launches == []
    assert (finished.id, "FINAL:answer") in h.sent
    assert h.store.rows[newest.id].session_id == "spawned-t1"  # assigning continues

    oldest = h.store.add(session_id=None, sent_at=100.0)
    intake()
    h.runner.run_pass()
    assert h.store.rows[oldest.id].status == store.STATUS_RUNNING
    assert h.store.rows[newest.id].status == store.STATUS_QUEUED


def test_ending_a_sync_wakes_the_runner(monkeypatch) -> None:
    woken: list[bool] = []
    monkeypatch.setattr(
        runner_module, "notify_email_runner", lambda: woken.append(True)
    )
    runner_module.begin_intake()
    assert runner_module.intake_in_progress()
    runner_module.end_intake()
    assert not runner_module.intake_in_progress()
    assert woken == [True]


def test_overlapping_syncs_hold_until_the_last_one_ends(monkeypatch) -> None:
    monkeypatch.setattr(runner_module, "notify_email_runner", lambda: None)
    runner_module.begin_intake()
    runner_module.begin_intake()
    runner_module.end_intake()
    assert runner_module.intake_in_progress()
    runner_module.end_intake()
    assert not runner_module.intake_in_progress()


# -- the queue row -----------------------------------------------------------


def _db_row(**overrides) -> dict:
    return {
        "id": 1,
        "agent_id": None,
        "session_id": "s1",
        "gmail_message_id": "m1",
        "gmail_thread_id": "t1",
        "alias": "agent@example.test",
        "sender_address": "person@example.test",
        "received_at": 2.0,
        "sent_at": 1.0,
        "status": "queued",
        **overrides,
    }


def test_single_session_row_has_no_agent() -> None:
    row = store._row(_db_row())
    assert row.agent_id is None
    assert row.session_id == "s1"
    assert row.sent_at == 1.0


@pytest.mark.parametrize(
    ("agent_id", "session_id"), [(None, "s1"), ("a1", None)], ids=["single", "pool"]
)
def test_insert_stores_the_owner_and_sent_date(
    monkeypatch, agent_id, session_id
) -> None:
    executed: list = []

    def execute(sql, params):
        executed.append((sql, params))
        return 1

    monkeypatch.setattr(store, "_execute", execute)
    inserted = store.insert_inbound(
        store.NewInboundEmail(
            agent_id=agent_id,
            session_id=session_id,
            gmail_message_id="m1",
            gmail_thread_id="t1",
            alias="agent@example.test",
            sender_address="person@example.test",
            sender_display_name=None,
            subject="Hello",
            message_id_header="<m1@mail.example.test>",
            references_header="",
            body_text="hi",
            received_at=2.0,
            sent_at=1.0,
        ),
        needs_queued_reply=False,
    )
    assert inserted is True
    sql, params = executed[0]
    columns = sql.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")
    values = dict(zip((c.strip() for c in columns), params, strict=True))
    assert values["agent_id"] == agent_id
    assert values["session_id"] == session_id
    assert values["received_at"] == 2.0
    assert values["sent_at"] == 1.0


def test_session_delete_removes_only_its_own_kind_of_row(monkeypatch) -> None:
    executed: list = []
    monkeypatch.setattr(
        store, "_execute", lambda sql, params: executed.append((sql, params))
    )
    store.delete_single_session_rows("s1")
    sql, params = executed[0]
    assert "agent_id IS NULL" in sql
    assert params == ("s1",)


def test_spawn_path_never_sees_single_session_rows(monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr(
        store, "_select", lambda where, params: seen.append(where) or []
    )
    store.queued_without_session()
    assert "agent_id IS NOT NULL" in seen[0]
