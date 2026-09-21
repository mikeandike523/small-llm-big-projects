"""
Single entry point for reading a slbp parameter's effective value.

Wraps KVManager.get_value() with the param_registry: an unset key resolves to
REGISTRY[name].default (already sanity-checked once at import time in
param_registry.py), and a value actually found in the DB is re-validated against
the same ParamSpec before being handed back. This replaces the ad hoc
`.get(x, <literal default>)` / `... or <literal default>` sprinkled across call
sites -- see param_defaults_checklist.md for the audit that motivated this.
"""

from __future__ import annotations

import logging
from typing import Any

from src.utils.param_registry import REGISTRY, param_storage_key
from src.utils.sql.kv_manager import KVManager

logger = logging.getLogger(__name__)

_UNSET = object()  # sentinel: distinguishes "no row in kv_store" from a stored `null`


def get_param_value(kv: KVManager, name: str, profile_prefix: str | None = None) -> Any:
    """Return the effective value of param `name`: the stored value if set and valid,
    else REGISTRY[name].default.

    Args:
        kv: an already-connected KVManager.
        name: registry param name, e.g. "system.strict_dirty".
        profile_prefix: required for profile-scoped params (e.g. "profiles.<name>.");
            omit for global-scoped params. See param_storage_key().

    Returns:
        The parsed value (same Python type as ParamSpec.parse_value would produce),
        or REGISTRY[name].default when nothing is stored. For "omittable" params
        (default=None), callers must treat None as "omit this from wherever it's
        being forwarded" -- get_param_value does not do that itself, since the right
        way to omit varies by call site (e.g. drop a dict key vs. skip a code path).

    Raises:
        ValueError: if `name` is not a registered param, if the param is
            profile-scoped and no `profile_prefix` was given, or if a value IS
            stored in the DB but fails ParamSpec validation (corrupt/stale data).
    """
    if name not in REGISTRY:
        raise ValueError(f"Unknown param '{name}'")
    spec = REGISTRY[name]
    key = param_storage_key(name, profile_prefix)

    raw = kv.get_value(key, default=_UNSET)
    if raw is _UNSET:
        return spec.default

    if raw is None:
        # An explicit stored null is only legitimate for params whose own default
        # is None (the "omittable" ones) -- for anything else, a null in the DB is
        # corrupt data, not a valid boolean/integer/string/object value.
        if spec.default is None:
            return None
        logger.error(
            "param_helper: '%s' is stored as null in the DB but has no null default "
            "(registry default=%r)",
            name,
            spec.default,
        )
        raise ValueError(
            "Data in database is not valid according to parameter registry. "
            "Please contact server administrator."
        )

    try:
        return spec.parse_value(raw)
    except ValueError as exc:
        logger.error(
            "param_helper: stored value for '%s' failed validation: %s", name, exc
        )
        raise ValueError(
            "Data in database is not valid according to parameter registry. "
            "Please contact server administrator."
        ) from exc
