"""Delegated Gmail API client factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.channels.email.config import EmailConfig
from src.channels.email.credentials import load_delegated_credentials


def build_gmail_client(config: EmailConfig, repo_root: Path | None = None) -> Any:
    _path, credentials = load_delegated_credentials(config, repo_root)
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)
