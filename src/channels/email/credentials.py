"""Repository-relative Gmail service-account credential validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.channels.email.config import EmailConfig

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE)


class EmailCredentialError(RuntimeError):
    """Raised when required email-channel credentials cannot be validated."""


def find_repo_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor containing a ``.git`` file or directory."""
    location = (start or Path(__file__)).resolve()
    directory = location if location.is_dir() else location.parent
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            return candidate
    raise EmailCredentialError(
        f"Email integration could not locate the repository root from {location}; "
        "no parent containing .git was found."
    )


def service_account_path(repo_root: Path | None = None) -> Path:
    root = repo_root or find_repo_root()
    return root / "credentials" / "service-account-key.json"


def _load_identity_fields(path: Path) -> tuple[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EmailCredentialError(
            f"Email integration is enabled, but the required service-account file "
            f"does not exist at {path}."
        ) from exc
    except OSError as exc:
        raise EmailCredentialError(
            f"Email integration is enabled, but the service-account file at {path} "
            f"cannot be read: {exc}."
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EmailCredentialError(
            f"Email integration is enabled, but the service-account file at {path} "
            f"is not valid JSON: {exc.msg}."
        ) from exc

    if not isinstance(payload, dict):
        raise EmailCredentialError(
            f"Email integration is enabled, but the service-account file at {path} "
            "must contain a JSON object."
        )

    required = ("type", "project_id", "client_email", "private_key")
    missing = [name for name in required if not payload.get(name)]
    if payload.get("type") != "service_account" or missing:
        detail = (
            f"missing required fields: {', '.join(missing)}"
            if missing
            else "the 'type' field is not 'service_account'"
        )
        raise EmailCredentialError(
            f"Email integration is enabled, but the service-account file at {path} "
            f"is malformed ({detail})."
        )
    return str(payload["project_id"]), str(payload["client_email"])


def load_delegated_credentials(
    config: EmailConfig, repo_root: Path | None = None
) -> tuple[Path, Any]:
    """Validate identity and construct delegated credentials without a network call."""
    path = service_account_path(repo_root)
    project_id, client_email = _load_identity_fields(path)
    if project_id != config.project_id:
        raise EmailCredentialError(
            "Gmail credential project_id does not match GMAIL_GOOGLE_CLOUD_PROJECT_ID"
        )
    if client_email.casefold() != config.processor_service_account_email.casefold():
        raise EmailCredentialError(
            "Gmail credential client_email does not match "
            "GMAIL_PROCESSOR_SERVICE_ACCOUNT_EMAIL"
        )
    try:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            str(path), scopes=list(GMAIL_SCOPES)
        ).with_subject(config.mailbox_email)
    except Exception as exc:
        raise EmailCredentialError(
            f"Gmail service-account credential at {path} could not be parsed: {exc}"
        ) from exc
    return path, credentials


def validate_service_account_file(
    config: EmailConfig, repo_root: Path | None = None
) -> Path:
    path, _credentials = load_delegated_credentials(config, repo_root)
    return path
