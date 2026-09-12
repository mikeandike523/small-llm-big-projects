from __future__ import annotations

APPROVAL_MODE_DEFAULT = "default"
APPROVAL_MODE_AUTO_ACCEPT_EDITS = "auto-accept-edits"
APPROVAL_MODE_FULL_AUTO = "full-auto"

APPROVAL_MODES = [
    APPROVAL_MODE_DEFAULT,
    APPROVAL_MODE_AUTO_ACCEPT_EDITS,
    APPROVAL_MODE_FULL_AUTO,
]


def is_valid_approval_mode(value: object) -> bool:
    return isinstance(value, str) and value in APPROVAL_MODES
