from __future__ import annotations

import re

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

_NO_PROFILE_HINT = (
    "No default profile selected. "
    "Use 'slbp profile new <name>' to create one and "
    "'slbp profile use <name>' to select it, "
    "or run 'slbp dashboard' to manage profiles visually."
)


def _kv_prefix(profile: str) -> str:
    return f"profiles.{profile}."


def get_active_profile(kv) -> str | None:
    """Return the active profile name, or None if no profile is selected."""
    val = kv.get_value("active_profile")
    return val if val else None


def require_active_profile(kv) -> str:
    """Return the active profile name or raise SystemExit with a helpful message."""
    profile = get_active_profile(kv)
    if profile is None:
        import click
        raise click.ClickException(_NO_PROFILE_HINT)
    return profile


def validate_profile_name(name: str) -> str | None:
    """Return an error message if the name is invalid, else None."""
    if not _PROFILE_NAME_RE.match(name):
        return f"Invalid profile name '{name}'. Names must match ^[a-zA-Z0-9_-]+$."
    return None
