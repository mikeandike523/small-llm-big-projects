from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

import src.channels.email as email_channel
import src.channels.email.credentials as credentials_module
import src.channels.email.watch_daemon as daemon_module
from src.channels.email.config import EmailConfig, EmailConfigError, load_email_config
from src.channels.email.credentials import EmailCredentialError, find_repo_root
from src.channels.email.state import GmailMailboxState
from src.channels.email.watch_daemon import EmailWatchDaemon, is_watch_refresh_due


def _config() -> EmailConfig:
    return EmailConfig(
        mailbox_email="mailbox@example.test",
        alias_email="assistant@example.test",
        project_id="example-project",
        processor_service_account_email=(
            "processor@example-project.iam.gserviceaccount.com"
        ),
        topic_resource="projects/example-project/topics/gmail-notifications",
        subscription_resource=(
            "projects/example-project/subscriptions/gmail-notifications-webhook"
        ),
        push_service_account_email=("push@example-project.iam.gserviceaccount.com"),
        push_audience="https://agent.example.test/webhooks/gmail",
    )


def _state(last_success: float | None) -> GmailMailboxState:
    return GmailMailboxState(
        mailbox_email="mailbox@example.test",
        last_processed_history_id="123",
        initialization_started_unix=1,
        watch_last_attempt_unix=last_success,
        watch_last_success_unix=last_success,
        watch_expiration_ms=None,
        watch_next_attempt_unix=None,
        watch_last_error=None,
        sync_last_attempt_unix=None,
        sync_last_success_unix=None,
        sync_last_error=None,
    )


def test_find_repo_root_accepts_git_file(tmp_path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    nested = tmp_path / "src" / "channels" / "email"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path


def test_service_account_file_is_required(tmp_path) -> None:
    with pytest.raises(EmailCredentialError, match="does not exist"):
        credentials_module._load_identity_fields(
            tmp_path / "credentials" / "service-account-key.json"
        )


def test_validate_service_account_delegates_without_exposing_contents(
    monkeypatch,
) -> None:
    expected = Path("credentials/service-account-key.json")
    monkeypatch.setattr(
        credentials_module,
        "load_delegated_credentials",
        lambda config, repo_root=None: (expected, object()),
    )
    assert credentials_module.validate_service_account_file(_config()) == expected


def test_config_requires_all_values() -> None:
    with pytest.raises(EmailConfigError, match="required environment variables"):
        load_email_config({})


def test_disabled_email_skips_all_initialization(monkeypatch) -> None:
    monkeypatch.setattr(email_channel, "is_email_enabled", lambda: False)
    monkeypatch.setattr(
        email_channel,
        "load_email_config",
        lambda: pytest.fail("config must not be inspected"),
    )
    assert email_channel.startup_email() is None


def test_enabled_email_credential_failure_is_fatal(monkeypatch, caplog) -> None:
    monkeypatch.setattr(email_channel, "is_email_enabled", lambda: True)
    monkeypatch.setattr(email_channel, "load_email_config", _config)
    monkeypatch.setattr(
        email_channel,
        "validate_service_account_file",
        lambda _config: (_ for _ in ()).throw(EmailCredentialError("missing key")),
    )
    with caplog.at_level(logging.CRITICAL), pytest.raises(
        EmailCredentialError, match="missing key"
    ):
        email_channel.startup_email()
    assert "Email integration startup failed: missing key" in caplog.text


def test_due_calculation_uses_last_success_and_retry_time() -> None:
    assert is_watch_refresh_due(_state(None), 100.0)
    assert not is_watch_refresh_due(_state(100.0), 100.0 + 86_399)
    assert is_watch_refresh_due(_state(100.0), 100.0 + 86_400)
    retry_state = GmailMailboxState(
        **{**_state(100.0).__dict__, "watch_next_attempt_unix": 500.0}
    )
    assert not is_watch_refresh_due(retry_state, 499.0)
    assert is_watch_refresh_due(retry_state, 500.0)


def test_daemon_checks_immediately_and_uses_interruptible_wait(monkeypatch) -> None:
    checked = threading.Event()
    monkeypatch.setattr(
        daemon_module,
        "load_mailbox_state",
        lambda _mailbox: checked.set() or _state(100.0),
    )
    monkeypatch.setattr(daemon_module, "pending_notification_count", lambda _mailbox: 0)
    monkeypatch.setattr(
        daemon_module, "synchronize_mailbox", lambda *_args, **_kwargs: True
    )
    daemon = EmailWatchDaemon(
        config=_config(),
        gmail_factory=lambda: object(),
        interval_seconds=60,
        wall_time=lambda: 101.0,
    )
    daemon.start()
    assert checked.wait(timeout=1)
    daemon.stop()
