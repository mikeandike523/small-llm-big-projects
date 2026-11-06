"""Validating what the agent dialog submits (name, email and settings)."""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.approval_modes import APPROVAL_MODES, is_valid_approval_mode
from src.utils.automation_approval_policies import AUTOMATION_APPROVAL_POLICIES
from src.utils.email_addresses import InvalidEmailAddressError, parse_email_address

AGENT_NAME_MAX_CHARS = 80
AGENT_ALLOWED_SENDERS_MAX = 200


class InvalidAgentSettingsError(ValueError):
    """User-supplied agent settings are invalid; ``str(exc)`` says why."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class AgentIdentity:
    name: str
    email: str

    @property
    def name_key(self) -> str:
        """Compared to find name conflicts, so ``Ana`` and ``ana`` clash."""
        return self.name.casefold()


@dataclass(frozen=True)
class AgentSettings:
    enabled: bool
    allowed_senders: list[str]
    profile_name: str
    approval_mode: str
    automation_approval_policy: str


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
        raise InvalidAgentSettingsError(
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
            raise InvalidAgentSettingsError(
                f"Allowed senders line {number} ({line.strip()!r}) {exc}",
                field="allowed_senders",
            ) from exc
        if address not in senders:
            senders.append(address)
    if len(senders) > AGENT_ALLOWED_SENDERS_MAX:
        raise InvalidAgentSettingsError(
            f"At most {AGENT_ALLOWED_SENDERS_MAX} allowed senders are supported",
            field="allowed_senders",
        )
    return senders


def parse_agent_identity(data: dict) -> AgentIdentity:
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InvalidAgentSettingsError("Agent name is required", field="name")
    name = name.strip()
    if len(name) > AGENT_NAME_MAX_CHARS:
        raise InvalidAgentSettingsError(
            f"Agent name must be at most {AGENT_NAME_MAX_CHARS} characters",
            field="name",
        )
    if any(ch in name for ch in '\r\n"<>'):
        raise InvalidAgentSettingsError(
            "Agent name must not contain line breaks, quotes or angle brackets",
            field="name",
        )
    raw_email = data.get("email")
    if not isinstance(raw_email, str) or not raw_email.strip():
        raise InvalidAgentSettingsError("Email address is required", field="email")
    try:
        email = parse_email_address(raw_email)
    except InvalidEmailAddressError as exc:
        raise InvalidAgentSettingsError(f"Email {exc}", field="email") from exc
    return AgentIdentity(name=name, email=email)


def parse_agent_settings(data: dict) -> AgentSettings:
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise InvalidAgentSettingsError("'enabled' must be a boolean", field="enabled")
    profile_name = data.get("profile_name")
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise InvalidAgentSettingsError("A profile is required", field="profile_name")
    approval_mode = data.get("approval_mode")
    if not is_valid_approval_mode(approval_mode):
        raise InvalidAgentSettingsError(
            "'approval_mode' must be one of: " + ", ".join(APPROVAL_MODES),
            field="approval_mode",
        )
    policy = data.get("automation_approval_policy")
    if policy not in AUTOMATION_APPROVAL_POLICIES:
        raise InvalidAgentSettingsError(
            "'automation_approval_policy' must be one of: "
            + ", ".join(AUTOMATION_APPROVAL_POLICIES),
            field="automation_approval_policy",
        )
    return AgentSettings(
        enabled=enabled,
        allowed_senders=parse_allowed_senders(data.get("allowed_senders", "")),
        profile_name=profile_name.strip(),
        approval_mode=approval_mode,
        automation_approval_policy=policy,
    )
