"""Repository-relative Gmail service-account credential validation."""

from __future__ import annotations

import json
from pathlib import Path


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


def validate_service_account_file(repo_root: Path | None = None) -> Path:
    """Validate the required JSON file without exposing any credential values."""
    path = service_account_path(repo_root)
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

    required = ("type", "client_email", "private_key")
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
    return path
