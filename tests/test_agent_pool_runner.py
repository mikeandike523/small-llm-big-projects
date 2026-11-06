"""The runner's agent-pool behavior (shares test_email_runner's harness)."""

from __future__ import annotations

import src.channels.email.email_runner as runner_module
import src.channels.email.inbound_store as store
from test_email_runner import Harness


def test_new_mail_gets_a_session_before_it_runs(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add(session_id=None)
    h.runner.run_pass()
    assert h.spawned == [row.id]
    assert h.store.rows[row.id].session_id == "spawned-t1"
    assert h.launches[0][0] == "spawned-t1"


def test_failed_spawn_leaves_the_mail_queued_for_a_later_pass(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add(session_id=None)

    def fail_once(_row):
        h.runner._assign_session = h._assign
        raise OSError("disk full")

    h.runner._assign_session = fail_once
    h.runner.run_pass()
    assert h.store.rows[row.id].session_id is None
    assert h.store.rows[row.id].status == store.STATUS_QUEUED
    assert h.launches == []
    h.runner.run_pass()
    assert h.launches[0][0] == "spawned-t1"


def test_conversations_run_in_parallel_and_stay_in_order(monkeypatch) -> None:
    h = Harness(monkeypatch)
    first = h.store.add(session_id="ana")
    h.store.add(session_id="ana")
    other = h.store.add(session_id="bob")
    h.runner.run_pass()
    assert sorted(launch[0] for launch in h.launches) == ["ana", "bob"]
    assert h.store.rows[first.id].status == store.STATUS_RUNNING
    assert h.store.rows[other.id].status == store.STATUS_RUNNING
    h.runner.run_pass()  # ana's second email waits for ana's first
    assert len(h.launches) == 2


def test_approval_notice_is_sent_once_regardless_of_the_param(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.params[runner_module.SYSTEM_MESSAGES_PARAM] = False
    row = h.store.add()
    h.runner.run_pass()
    h.store.approval_requested.add(row.id)
    h.runner.run_pass()
    h.runner.run_pass()
    assert h.sent == [
        (
            row.id,
            "[Helper is awaiting approval on the system UI. If you were not "
            "expecting this message, please contact system administrator Sam "
            "Admin at mailto:admin@example.test]",
        )
    ]


def test_failed_approval_notice_is_retried(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.params[runner_module.SYSTEM_MESSAGES_PARAM] = False
    row = h.store.add()
    h.runner.run_pass()
    h.store.approval_requested.add(row.id)
    h.send_fails = True
    h.runner.run_pass()
    assert h.store.rows[row.id].approval_notice_sent_at is None
    h.send_fails = False
    h.runner.run_pass()
    assert h.store.rows[row.id].approval_notice_sent_at == 50.0


def test_approval_wait_is_only_recorded_for_email_turns(monkeypatch) -> None:
    from src.ui_connector.socket_handler_components import state
    from src.utils.session_model import SUBTURN_ORIGIN_EMAIL, SUBTURN_ORIGIN_USER

    recorded: list[str] = []
    monkeypatch.setattr(
        store,
        "request_approval_notice",
        lambda sid, _at: recorded.append(sid) or 1,
    )
    monkeypatch.setattr(
        state,
        "reserved_turn_origin",
        lambda sid: SUBTURN_ORIGIN_EMAIL if sid == "mail" else SUBTURN_ORIGIN_USER,
    )
    runner_module.on_approval_wait("human")
    runner_module.on_approval_wait("mail")
    assert recorded == ["mail"]
