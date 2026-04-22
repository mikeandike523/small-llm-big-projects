from __future__ import annotations

import re

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _kv_prefix(profile: str) -> str:
    return "" if profile == "default" else f"profiles.{profile}."


def get_active_profile(kv) -> str:
    """Read active_profile from kv_store. Absence implies 'default'."""
    val = kv.get_value("active_profile")
    return val if val else "default"


def validate_profile_name(name: str) -> str | None:
    """Return an error message if the name is invalid, else None."""
    if name.lower() == "default":
        return "'default' is a reserved profile name."
    if not _PROFILE_NAME_RE.match(name):
        return f"Invalid profile name '{name}'. Names must match ^[a-zA-Z0-9_-]+$."
    return None
