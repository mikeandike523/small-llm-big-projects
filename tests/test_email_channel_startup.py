from __future__ import annotations

import json
import logging
import threading

import pytest

import src.channels.email as email_channel
from src.channels.email.credentials import (
    EmailCredentialError,
    find_repo_root,
    validate_service_account_file,
)
from src.channels.email.watch_daemon import EmailWatchDaemon, is_watch_refresh_due
from src.channels.email.watch_state import GmailWatchState


def _state(last_success: float | None) -> GmailWatchState:
    return GmailWatchState(None, last_success, None, None, None)


def test_find_repo_root_accepts_git_file(tmp_path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    nested = tmp_path / "src" / "channels" / "email"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path


def test_service_account_file_is_required_and_parsed(tmp_path) -> None:
    with pytest.raises(EmailCredentialError, match="does not exist"):
        validate_service_account_file(tmp_path)

    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    path = credential_dir / "service-account-key.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(EmailCredentialError, match="not valid JSON"):
        validate_service_account_file(tmp_path)

    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "client_email": "gmail@example.test",
                "private_key": "secret",
            }
        ),
        encoding="utf-8",
    )
    assert validate_service_account_file(tmp_path) == path


def test_disabled_email_skips_credentials_state_and_daemon(monkeypatch) -> None:
    monkeypatch.setattr(email_channel, "_is_email_enabled", lambda: False)
    monkeypatch.setattr(
        email_channel,
        "validate_service_account_file",
        lambda: pytest.fail("credentials must not be inspected"),
    )
    monkeypatch.setattr(
        email_channel,
        "load_gmail_watch_state",
        lambda: pytest.fail("state must not be loaded"),
    )
    assert email_channel.startup_email() is None


def test_enabled_email_credential_failure_is_fatal(monkeypatch, caplog) -> None:
    monkeypatch.setattr(email_channel, "_is_email_enabled", lambda: True)
    monkeypatch.setattr(
        email_channel,
        "validate_service_account_file",
        lambda: (_ for _ in ()).throw(EmailCredentialError("missing key")),
    )
    with caplog.at_level(logging.CRITICAL), pytest.raises(
        EmailCredentialError, match="missing key"
    ):
        email_channel.startup_email()
    assert "Email integration startup failed: missing key" in caplog.text


def test_due_calculation_uses_last_success() -> None:
    assert is_watch_refresh_due(None, 100.0)
    assert not is_watch_refresh_due(100.0, 100.0 + 86_399)
    assert is_watch_refresh_due(100.0, 100.0 + 86_400)


def test_daemon_checks_immediately_and_uses_interruptible_wait() -> None:
    checked = threading.Event()
    daemon = EmailWatchDaemon(
        state_provider=lambda: checked.set() or _state(None),
        interval_seconds=60,
    )
    daemon.start()
    assert checked.wait(timeout=1)
    daemon.stop()
