from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

import src.channels.email.email_runner as runner_module
import src.channels.email.inbound_store as store
from src.channels.email.config import EmailConfig
from src.channels.email.inbound_store import InboundEmail
from src.ui_connector.socket_handler_components.turn_outcome import TurnOutcome
from src.utils.email_settings import DEFAULT_EMAIL_SETTINGS
from src.utils.param_registry import REGISTRY


class FakeStore:
    """In-memory stand-in for inbound_store's MySQL functions."""

    def __init__(self) -> None:
        self.rows: dict[int, InboundEmail] = {}
        self._ids = itertools.count(1)

    def add(self, **overrides) -> InboundEmail:
        row_id = next(self._ids)
        row = InboundEmail(
            id=row_id,
            session_id="s1",
            gmail_message_id=f"m{row_id}",
            gmail_thread_id="t1",
            alias="agent@example.test",
            sender_address="person@example.test",
            subject="Hello",
            message_id_header=f"<m{row_id}@mail.example.test>",
            references_header="",
            body_text=f"body {row_id}",
            received_at=float(row_id),
            status=store.STATUS_QUEUED,
            needs_queued_reply=False,
            queued_reply_sent_at=None,
            working_reply_sent_at=None,
            final_reply_sent_at=None,
            final_text=None,
            error_detail=None,
        )
        row = replace(row, **overrides)
        self.rows[row_id] = row
        return row

    def _set(self, row_id: int, **changes) -> None:
        self.rows[row_id] = replace(self.rows[row_id], **changes)

    def install(self, monkeypatch) -> None:
        ordered = lambda rows: sorted(rows, key=lambda r: (r.received_at, r.id))
        m = monkeypatch.setattr

        def mark_orphaned_interrupted():
            running = [
                r.id for r in self.rows.values() if r.status == store.STATUS_RUNNING
            ]
            for row_id in running:
                self._set(row_id, status=store.STATUS_INTERRUPTED)
            return len(running)

        m(store, "mark_orphaned_interrupted", mark_orphaned_interrupted)
        m(
            store,
            "sessions_with_pending_work",
            lambda: sorted({r.session_id for r in self.rows.values()}),
        )
        m(
            store,
            "finished_needing_final_reply",
            lambda sid: ordered(
                r
                for r in self.rows.values()
                if r.session_id == sid
                and r.status in store.FINISHED_STATUSES
                and r.final_reply_sent_at is None
            ),
        )
        m(
            store,
            "queued_needing_queued_reply",
            lambda sid: ordered(
                r
                for r in self.rows.values()
                if r.session_id == sid
                and r.status == store.STATUS_QUEUED
                and r.needs_queued_reply
                and r.queued_reply_sent_at is None
            ),
        )

        def oldest(sid):
            queued = ordered(
                r
                for r in self.rows.values()
                if r.session_id == sid and r.status == store.STATUS_QUEUED
            )
            return queued[0] if queued else None

        def try_mark_running(row_id):
            if self.rows[row_id].status != store.STATUS_QUEUED:
                return False
            self._set(row_id, status=store.STATUS_RUNNING)
            return True

        def mark_finished(row_id, status, *, final_text=None, error_detail=None):
            if self.rows[row_id].status == store.STATUS_RUNNING:
                self._set(
                    row_id,
                    status=status,
                    final_text=final_text,
                    error_detail=error_detail,
                )

        m(store, "oldest_queued", oldest)
        m(store, "try_mark_running", try_mark_running)
        m(store, "requeue", lambda rid: self._set(rid, status=store.STATUS_QUEUED))
        m(store, "mark_finished", mark_finished)
        m(
            store,
            "mark_reply_sent",
            lambda rid, column, at: self._set(rid, **{column: at}),
        )


class Harness:
    def __init__(self, monkeypatch, *, launch_results=None, send_fails=False):
        self.store = FakeStore()
        self.store.install(monkeypatch)
        self.sent: list[tuple[int, str]] = []
        self.launches: list[tuple[str, str, str]] = []
        self.callbacks: list = []
        self.launch_results = iter(launch_results or itertools.repeat(True))
        self.send_fails = send_fails
        self.settings = {
            **DEFAULT_EMAIL_SETTINGS,
            "enabled": True,
            "alias": "agent@example.test",
            "agent_name": "Helper",
            "followup_behavior": "new-task",
        }
        self.params = {
            runner_module.SYSTEM_MESSAGES_PARAM: True,
            runner_module.ADMIN_NAME_PARAM: "Sam Admin",
            runner_module.ADMIN_EMAIL_PARAM: "admin@example.test",
        }
        monkeypatch.setattr(runner_module, "send_message", self._send)
        monkeypatch.setattr(runner_module, "log_google_error", lambda *a, **k: None)
        self.runner = runner_module.EmailRunner(
            config=EmailConfig(
                mailbox_email="mailbox@example.test",
                system_alias_address="system@example.test",
                system_alias_name="Example System",
                project_id="p",
                processor_service_account_email="proc@example.test",
                topic_resource="projects/p/topics/t",
                subscription_resource="projects/p/subscriptions/s",
                push_service_account_email="push@example.test",
                push_audience="https://agent.example.test/webhooks/gmail",
            ),
            gmail_factory=lambda: object(),
            launch=self._launch,
            settings_for=lambda _sid: self.settings,
            read_param=lambda name: self.params[name],
            clock=lambda: 50.0,
        )

    def _launch(self, session_id, text, behavior, on_finished) -> bool:
        self.launches.append((session_id, text, behavior))
        result = next(self.launch_results)
        if result:
            self.callbacks.append(on_finished)
        return result

    def _send(self, _gmail, anchor, message) -> dict:
        if self.send_fails:
            raise RuntimeError("network down")
        if message.get_content_type() == "multipart/alternative":
            body = "FINAL:" + message.get_body(("plain",)).get_content().strip()
        else:
            body = message.get_content().strip()
        self.sent.append((anchor.id, body))
        return {}


def test_idle_email_is_launched_with_working_note(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add()
    h.runner.run_pass()
    assert h.launches[0][0] == "s1"
    assert h.launches[0][2] == "new-task"
    assert h.launches[0][1].startswith(
        '[Email from person@example.test, subject "Hello"'
    )
    assert h.sent == [(row.id, "[Helper is working...]")]
    assert h.store.rows[row.id].status == store.STATUS_RUNNING


def test_final_answer_is_sent_after_turn_finishes(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add()
    h.runner.run_pass()
    h.callbacks[0](TurnOutcome(final_text="**Answer**"))
    h.runner.run_pass()
    assert h.sent[-1] == (row.id, "FINAL:**Answer**")
    assert h.store.rows[row.id].status == store.STATUS_DONE
    assert h.store.rows[row.id].final_reply_sent_at == 50.0


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (TurnOutcome(cancelled=True), "[Helper's task was cancelled in session UI]"),
        (
            TurnOutcome.failed("model offline"),
            "[Helper had a network or system error. Please contact system "
            "administrator Sam Admin at mailto:admin@example.test]",
        ),
    ],
)
def test_cancel_and_failure_replies(monkeypatch, outcome, expected) -> None:
    h = Harness(monkeypatch)
    row = h.store.add()
    h.runner.run_pass()
    h.callbacks[0](outcome)
    h.runner.run_pass()
    assert h.sent[-1] == (row.id, expected)


def test_turn_running_at_startup_is_reported_as_interrupted(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add(status=store.STATUS_RUNNING)
    h.runner.start()
    h.runner.stop()
    h.runner.run_pass()
    assert h.store.rows[row.id].status == store.STATUS_INTERRUPTED
    assert h.sent == [
        (
            row.id,
            "[Turn interrupted. You can re-send your message by replying to this email.]",
        )
    ]
    assert h.launches == []


def test_emails_run_one_at_a_time_in_order(monkeypatch) -> None:
    h = Harness(monkeypatch)
    first = h.store.add()
    second = h.store.add(needs_queued_reply=True)
    h.runner.run_pass()
    assert (second.id, "[message queued]") in h.sent
    assert len(h.launches) == 1
    h.runner.run_pass()  # first still running: nothing new starts
    assert len(h.launches) == 1
    h.callbacks[0](TurnOutcome(final_text="one"))
    h.runner.run_pass()
    assert len(h.launches) == 2
    assert h.sent[-2:] == [
        (first.id, "FINAL:one"),
        (second.id, "[Helper is working...]"),
    ]


def test_busy_session_requeues_and_sends_queued_note_once(monkeypatch) -> None:
    h = Harness(monkeypatch, launch_results=[False, False, True])
    row = h.store.add()
    h.runner.run_pass()
    h.runner.run_pass()
    assert h.store.rows[row.id].status == store.STATUS_QUEUED
    assert h.sent == [(row.id, "[message queued]")]
    h.runner.run_pass()
    assert h.sent[-1] == (row.id, "[Helper is working...]")


def test_failed_send_is_retried_on_next_pass(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add()
    h.runner.run_pass()
    h.callbacks[0](TurnOutcome(final_text="answer"))
    h.send_fails = True
    h.runner.run_pass()
    assert h.store.rows[row.id].final_reply_sent_at is None
    h.send_fails = False
    h.runner.run_pass()
    assert h.sent[-1] == (row.id, "FINAL:answer")


def test_progress_notes_off_leaves_only_the_final_reply(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.params[runner_module.SYSTEM_MESSAGES_PARAM] = False
    first = h.store.add()
    second = h.store.add(needs_queued_reply=True)
    h.runner.run_pass()
    assert h.sent == []
    h.callbacks[0](TurnOutcome(final_text="one"))
    h.runner.run_pass()
    assert h.sent == [(first.id, "FINAL:one")]
    assert h.store.rows[second.id].status == store.STATUS_RUNNING


def test_progress_notes_off_when_session_is_busy(monkeypatch) -> None:
    h = Harness(monkeypatch, launch_results=[False, True])
    h.params[runner_module.SYSTEM_MESSAGES_PARAM] = False
    row = h.store.add()
    h.runner.run_pass()
    assert h.store.rows[row.id].status == store.STATUS_QUEUED
    assert h.sent == []
    h.runner.run_pass()
    assert h.store.rows[row.id].status == store.STATUS_RUNNING
    assert h.sent == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (store.STATUS_CANCELLED, "[Helper's task was cancelled in session UI]"),
        (
            store.STATUS_INTERRUPTED,
            "[Turn interrupted. You can re-send your message by replying to this email.]",
        ),
        (
            store.STATUS_FAILED,
            "[Helper had a network or system error. Please contact system "
            "administrator Sam Admin at mailto:admin@example.test]",
        ),
    ],
)
def test_progress_notes_off_keeps_end_of_turn_notes(
    monkeypatch, status, expected
) -> None:
    h = Harness(monkeypatch)
    h.params[runner_module.SYSTEM_MESSAGES_PARAM] = False
    row = h.store.add(status=status)
    h.runner.run_pass()
    assert h.sent == [(row.id, expected)]


@pytest.mark.parametrize(
    ("name", "address", "contact"),
    [
        ("Sam", "a@example.test", "system administrator Sam at mailto:a@example.test"),
        ("Sam", None, "system administrator Sam"),
        (None, "a@example.test", "your system administrator at mailto:a@example.test"),
        (None, None, "your system administrator"),
        ("  ", "", "your system administrator"),
    ],
)
def test_failed_note_contact_fallbacks(name, address, contact) -> None:
    assert (
        runner_module.failed_note("Helper", name, address)
        == f"[Helper had a network or system error. Please contact {contact}]"
    )


def test_failed_turn_keeps_the_error_detail_out_of_the_email(monkeypatch) -> None:
    h = Harness(monkeypatch)
    row = h.store.add()
    h.runner.run_pass()
    h.callbacks[0](TurnOutcome.failed("Check your API token"))
    h.runner.run_pass()
    assert "API token" not in h.sent[-1][1]
    assert h.store.rows[row.id].error_detail == "Check your API token"


def test_new_params_are_global_with_the_requested_defaults() -> None:
    enabled = REGISTRY[runner_module.SYSTEM_MESSAGES_PARAM]
    assert (enabled.scope, enabled.default) == ("global", False)
    for name in (runner_module.ADMIN_NAME_PARAM, runner_module.ADMIN_EMAIL_PARAM):
        assert (REGISTRY[name].scope, REGISTRY[name].default) == ("global", None)


def test_missing_agent_name_uses_generic_label(monkeypatch) -> None:
    h = Harness(monkeypatch)
    h.settings["agent_name"] = ""
    row = h.store.add()
    h.runner.run_pass()
    assert h.sent == [(row.id, "[The agent is working...]")]
