"""Per-session email channel settings (mirrors ``heartbeat_settings.py``).

Stored whole in ``email_settings_set`` events and in
``session.session_data["email_settings"]``; the alias claim is also copied to
``session_meta`` (``email_alias`` is UNIQUE there) so inbound routing and the
dashboard never need to load a session.
"""

from __future__ import annotations

from src.utils.automation_approval_policies import (
    AUTOMATION_APPROVAL_POLICIES,
    AUTOMATION_APPROVAL_POLICY_WAIT_FOR_HUMAN,
    AUTOMATION_FOLLOWUP_AUTO,
    AUTOMATION_FOLLOWUP_BEHAVIORS,
)
from src.utils.email_addresses import InvalidEmailAddressError, parse_email_address

EMAIL_AGENT_NAME_MAX_CHARS = 80
EMAIL_ALLOWED_SENDERS_MAX = 200

DEFAULT_EMAIL_SETTINGS = {
    "enabled": False,
    # "" means no alias claimed: the session replies to nobody.
    "alias": "",
    "agent_name": "",
    "allowed_senders": [],
    "email_approval_policy": AUTOMATION_APPROVAL_POLICY_WAIT_FOR_HUMAN,
    "followup_behavior": AUTOMATION_FOLLOWUP_AUTO,
    # Server-set unix time of the current alias claim; mail Gmail received
    # before it is ignored. None while no alias is claimed.
    "alias_claimed_at": None,
}


class InvalidEmailSettingsError(ValueError):
    """User-supplied email settings are invalid; ``str(exc)`` says why."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


def normalize_email_settings(value: dict | None) -> dict:
    """Stored settings with defaults filled in for fields added later."""
    return {**DEFAULT_EMAIL_SETTINGS, **(value or {})}


def parse_allowed_senders(raw: object) -> list[str]:
    """One address per line -> normalized, de-duplicated list (order kept).

    Accepts the textarea text or an already-split list. Blank lines are
    skipped; any other invalid line raises naming the line and the reason.
    """
    if isinstance(raw, str):
        lines = raw.splitlines()
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        lines = raw
    else:
        raise InvalidEmailSettingsError(
            "'allowed_senders' must be text with one address per line",
            field="allowed_senders",
        )
    senders: list[str] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            address = parse_email_address(line)
        except InvalidEmailAddressError as exc:
            raise InvalidEmailSettingsError(
                f"Allowed senders line {number} ({line.strip()!r}) {exc}",
                field="allowed_senders",
            ) from exc
        if address not in senders:
            senders.append(address)
    if len(senders) > EMAIL_ALLOWED_SENDERS_MAX:
        raise InvalidEmailSettingsError(
            f"At most {EMAIL_ALLOWED_SENDERS_MAX} allowed senders are supported",
            field="allowed_senders",
        )
    return senders


def parse_email_settings_input(data: dict) -> dict:
    """Validate a full-replace request body into settings (claim time unset).

    ``alias_claimed_at`` is never taken from the client; the caller sets it.
    """
    if not isinstance(data, dict):
        raise InvalidEmailSettingsError("settings must be an object", field="")

    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise InvalidEmailSettingsError("'enabled' must be a boolean", field="enabled")

    raw_alias = data.get("alias")
    if raw_alias is None:
        raw_alias = ""
    if not isinstance(raw_alias, str):
        raise InvalidEmailSettingsError("'alias' must be a string", field="alias")
    alias = ""
    if raw_alias.strip():
        try:
            alias = parse_email_address(raw_alias)
        except InvalidEmailAddressError as exc:
            raise InvalidEmailSettingsError(f"Alias {exc}", field="alias") from exc

    agent_name = data.get("agent_name")
    if agent_name is None:
        agent_name = ""
    if not isinstance(agent_name, str):
        raise InvalidEmailSettingsError(
            "'agent_name' must be a string", field="agent_name"
        )
    agent_name = agent_name.strip()
    if len(agent_name) > EMAIL_AGENT_NAME_MAX_CHARS:
        raise InvalidEmailSettingsError(
            f"Agent name must be at most {EMAIL_AGENT_NAME_MAX_CHARS} characters",
            field="agent_name",
        )
    if any(ch in agent_name for ch in '\r\n"<>'):
        raise InvalidEmailSettingsError(
            "Agent name must not contain line breaks, quotes or angle brackets",
            field="agent_name",
        )

    policy = data.get("email_approval_policy")
    if policy not in AUTOMATION_APPROVAL_POLICIES:
        raise InvalidEmailSettingsError(
            "'email_approval_policy' must be one of: "
            + ", ".join(AUTOMATION_APPROVAL_POLICIES),
            field="email_approval_policy",
        )

    behavior = data.get("followup_behavior")
    if behavior not in AUTOMATION_FOLLOWUP_BEHAVIORS:
        raise InvalidEmailSettingsError(
            "'followup_behavior' must be one of: "
            + ", ".join(AUTOMATION_FOLLOWUP_BEHAVIORS),
            field="followup_behavior",
        )

    return {
        "enabled": enabled,
        "alias": alias,
        "agent_name": agent_name,
        "allowed_senders": parse_allowed_senders(data.get("allowed_senders", "")),
        "email_approval_policy": policy,
        "followup_behavior": behavior,
        "alias_claimed_at": None,
    }


def email_agent_label(settings: dict) -> str:
    """The agent's name for status replies; falls back to a generic label."""
    return str(settings.get("agent_name") or "").strip() or "The agent"


# Appended to the system prompt while a session's email channel is enabled
# (llm._build_llm_payload reads the live setting on every request).
EMAIL_MULTITASK_PROMPT_NOTE = (
    "You may have to respond to several emails in sequence, meaning you may "
    "need to multitask or context-switch; don't be alarmed. Each email "
    "message starts with an [Email from ...] header naming its sender and "
    "subject."
)
