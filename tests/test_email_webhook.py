from __future__ import annotations

import base64
import json

from src.channels.email import webhook
from src.channels.email.config import EmailConfig
from src.ui_connector.app import app


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


def _payload() -> dict:
    data = base64.b64encode(
        json.dumps(
            {"emailAddress": "mailbox@example.test", "historyId": "123"}
        ).encode()
    ).decode()
    return {
        "subscription": (
            "projects/example-project/subscriptions/gmail-notifications-webhook"
        ),
        "message": {"messageId": "pubsub-1", "data": data},
    }


def test_authenticated_push_is_persisted_before_acknowledgement(monkeypatch) -> None:
    persisted = []
    woke = []
    monkeypatch.setattr(webhook, "get_email_config", _config)
    monkeypatch.setattr(
        webhook,
        "verify_push_identity",
        lambda _token, _audience: {
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "email": "push@example-project.iam.gserviceaccount.com",
        },
    )
    monkeypatch.setattr(
        webhook, "enqueue_notification", lambda value: persisted.append(value) or True
    )
    monkeypatch.setattr(webhook, "notify_email_work", lambda: woke.append(True))

    response = app.test_client().post(
        "/webhooks/gmail",
        json=_payload(),
        headers={"Authorization": "Bearer signed-token"},
    )
    assert response.status_code == 204
    assert persisted[0].notified_history_id == "123"
    assert woke == [True]


def test_push_without_google_identity_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(webhook, "get_email_config", _config)
    response = app.test_client().post("/webhooks/gmail", json=_payload())
    assert response.status_code == 401


def test_push_from_wrong_service_account_is_forbidden(monkeypatch) -> None:
    monkeypatch.setattr(webhook, "get_email_config", _config)
    monkeypatch.setattr(
        webhook,
        "verify_push_identity",
        lambda _token, _audience: {
            "iss": "accounts.google.com",
            "email_verified": True,
            "email": "attacker@example.test",
        },
    )
    response = app.test_client().post(
        "/webhooks/gmail",
        json=_payload(),
        headers={"Authorization": "Bearer signed-token"},
    )
    assert response.status_code == 403


def _authenticated(monkeypatch, persisted: list) -> None:
    monkeypatch.setattr(webhook, "get_email_config", _config)
    monkeypatch.setattr(
        webhook,
        "verify_push_identity",
        lambda _token, _audience: {
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "email": "push@example-project.iam.gserviceaccount.com",
        },
    )
    monkeypatch.setattr(
        webhook, "enqueue_notification", lambda value: persisted.append(value) or True
    )
    monkeypatch.setattr(webhook, "notify_email_work", lambda: None)


def _post(payload: dict):
    return app.test_client().post(
        "/webhooks/gmail",
        json=payload,
        headers={"Authorization": "Bearer signed-token"},
    )


def test_authenticated_malformed_push_is_acked_and_dropped(monkeypatch) -> None:
    persisted: list = []
    _authenticated(monkeypatch, persisted)
    payload = _payload()
    payload["message"]["data"] = "not base64 json!!"
    response = _post(payload)
    assert response.status_code == 204
    assert persisted == []


def test_authenticated_push_for_other_mailbox_is_acked_and_dropped(
    monkeypatch,
) -> None:
    persisted: list = []
    _authenticated(monkeypatch, persisted)
    payload = _payload()
    payload["message"]["data"] = base64.b64encode(
        json.dumps({"emailAddress": "other@example.test", "historyId": "9"}).encode()
    ).decode()
    response = _post(payload)
    assert response.status_code == 204
    assert persisted == []


def test_persistence_failure_is_retried(monkeypatch) -> None:
    _authenticated(monkeypatch, [])

    def fail(_value):
        raise ConnectionError("mysql down")

    monkeypatch.setattr(webhook, "enqueue_notification", fail)
    assert _post(_payload()).status_code == 503


def _outcome(response) -> dict:
    return json.loads(response.headers[webhook.OUTCOME_HEADER])


def test_outcome_header_reports_verdict_for_recorder(monkeypatch) -> None:
    _authenticated(monkeypatch, [])
    accepted = _post(_payload())
    assert _outcome(accepted) == {
        "result": "accepted",
        "reason": None,
        "pubsub_message_id": "pubsub-1",
        "history_id": "123",
    }

    payload = _payload()
    payload["message"]["data"] = "not base64 json!!"
    assert _outcome(_post(payload))["result"] == "dropped"


def test_outcome_header_on_auth_failure_and_disabled(monkeypatch) -> None:
    monkeypatch.setattr(webhook, "get_email_config", _config)
    unauthorized = app.test_client().post("/webhooks/gmail", json=_payload())
    assert _outcome(unauthorized)["result"] == "unauthorized"

    monkeypatch.setattr(webhook, "get_email_config", lambda: None)
    disabled = _post(_payload())
    assert disabled.status_code == 404
    assert _outcome(disabled)["result"] == "disabled"
