from __future__ import annotations

HEARTBEAT_INTERVALS_MINUTES = [5, 15, 20, 25, 30, 45, 60, 60 * 2, 60 * 3, 60 * 6, 60 * 9, 60 * 12, 60 * 15, 60 * 16, 60 * 24]
HEARTBEAT_INTERVAL_DEFAULT = 30

HEARTBEAT_APPROVAL_POLICY_WAIT_FOR_HUMAN = "wait-for-human"
HEARTBEAT_APPROVAL_POLICY_FORCE_FAIL = "force-fail"
HEARTBEAT_APPROVAL_POLICY_FORCE_APPROVE = "force-approve"

def get_heartbeat_intervals_payload() -> dict:
    """Return the source-of-truth interval list + default for the frontend."""
    return {
        "intervals": HEARTBEAT_INTERVALS_MINUTES,
        "default": HEARTBEAT_INTERVAL_DEFAULT,
    }


HEARTBEAT_APPROVAL_POLICIES = [
    HEARTBEAT_APPROVAL_POLICY_WAIT_FOR_HUMAN,
    HEARTBEAT_APPROVAL_POLICY_FORCE_FAIL,
    HEARTBEAT_APPROVAL_POLICY_FORCE_APPROVE,
]

DEFAULT_HEARTBEAT_SETTINGS = {
    "enabled": False,
    "interval_minutes": HEARTBEAT_INTERVAL_DEFAULT,
    "instructions": "",
    "heartbeat_approval_policy": HEARTBEAT_APPROVAL_POLICY_WAIT_FOR_HUMAN,
}


def is_valid_heartbeat_settings(value: object) -> tuple[bool, str | None]:
    if not isinstance(value, dict):
        return False, "heartbeat settings must be an object"

    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        return False, "'enabled' must be a boolean"

    interval_minutes = value.get("interval_minutes")
    if interval_minutes not in HEARTBEAT_INTERVALS_MINUTES:
        return (
            False,
            f"'interval_minutes' must be one of: {', '.join(str(i) for i in HEARTBEAT_INTERVALS_MINUTES)}",
        )

    instructions = value.get("instructions")
    if not isinstance(instructions, str):
        return False, "'instructions' must be a string"

    heartbeat_approval_policy = value.get("heartbeat_approval_policy")
    if heartbeat_approval_policy not in HEARTBEAT_APPROVAL_POLICIES:
        return (
            False,
            f"'heartbeat_approval_policy' must be one of: {', '.join(HEARTBEAT_APPROVAL_POLICIES)}",
        )

    return True, None
