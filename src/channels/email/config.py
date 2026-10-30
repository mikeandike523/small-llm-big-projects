"""Environment-backed configuration for the Gmail channel."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass


class EmailConfigError(RuntimeError):
    """Raised when enabled email-channel configuration is invalid."""


@dataclass(frozen=True)
class EmailConfig:
    mailbox_email: str
    alias_email: str
    project_id: str
    processor_service_account_email: str
    topic_resource: str
    subscription_resource: str
    push_service_account_email: str
    push_audience: str


_ENV_FIELDS = {
    "GMAIL_MAILBOX_EMAIL": "mailbox_email",
    "GMAIL_ALIAS_EMAIL": "alias_email",
    "GMAIL_GOOGLE_CLOUD_PROJECT_ID": "project_id",
    "GMAIL_PROCESSOR_SERVICE_ACCOUNT_EMAIL": "processor_service_account_email",
    "GMAIL_PUBSUB_TOPIC_RESOURCE": "topic_resource",
    "GMAIL_PUBSUB_SUBSCRIPTION_RESOURCE": "subscription_resource",
    "GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL": "push_service_account_email",
    "GMAIL_PUSH_AUDIENCE": "push_audience",
}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+$")


def load_email_config(environ: Mapping[str, str] | None = None) -> EmailConfig:
    source = os.environ if environ is None else environ
    missing = [name for name in _ENV_FIELDS if not str(source.get(name, "")).strip()]
    if missing:
        raise EmailConfigError(
            "Email integration is enabled, but required environment variables are "
            f"missing: {', '.join(missing)}"
        )
    values = {field: str(source[name]).strip() for name, field in _ENV_FIELDS.items()}
    config = EmailConfig(**values)
    for label, value in (
        ("GMAIL_MAILBOX_EMAIL", config.mailbox_email),
        ("GMAIL_ALIAS_EMAIL", config.alias_email),
        (
            "GMAIL_PROCESSOR_SERVICE_ACCOUNT_EMAIL",
            config.processor_service_account_email,
        ),
        ("GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL", config.push_service_account_email),
    ):
        if not _EMAIL_RE.match(value):
            raise EmailConfigError(f"{label} is not a valid email address")
    if not config.topic_resource.startswith(f"projects/{config.project_id}/topics/"):
        raise EmailConfigError(
            "GMAIL_PUBSUB_TOPIC_RESOURCE does not belong to the configured project"
        )
    if not config.subscription_resource.startswith(
        f"projects/{config.project_id}/subscriptions/"
    ):
        raise EmailConfigError(
            "GMAIL_PUBSUB_SUBSCRIPTION_RESOURCE does not belong to the configured project"
        )
    if not config.push_audience.startswith("https://"):
        raise EmailConfigError("GMAIL_PUSH_AUDIENCE must be an HTTPS URL")
    return config
