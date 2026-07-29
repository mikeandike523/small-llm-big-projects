import json

import click
from termcolor import colored

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import require_active_profile, _kv_prefix
from src.utils.param_registry import (
    ALLOWED_PARAMS as _ALLOWED_PARAMS,
    GLOBAL_PARAMS as _GLOBAL_PARAMS,
    REGISTRY as _REGISTRY,
    parse_param_value as _parse_param_value_registry,
    param_storage_key as _param_storage_key,
)

_NS_LABELS = {
    "model": "Main agentic loop (streaming calls)",
    "watchdog.model": "Watchdog samplers (YES/NO answers, task titles, skill selection)",
    "summarizer.model": "Summarizer samplers (subturn compaction, summarize_memory_item tool)",
    "patchrewriter.model": "Patch-rewriter sampler (unified diff repair)",
    "system": "System / infrastructure",
}


def _param_ns(name: str) -> str:
    """Return the display namespace for a param name."""
    parts = name.split(".")
    # e.g. "watchdog.model.temperature" -> "watchdog.model"
    for length in (3, 2, 1):
        candidate = ".".join(parts[:length])
        if candidate in _NS_LABELS:
            return candidate
    return parts[0]


def _parse_and_validate(name: str, raw_value: str):
    """Parse and validate a param value from CLI string input. Raises click.BadParameter on failure."""
    try:
        return _parse_param_value_registry(name, raw_value)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="value") from exc


def _list_set_params(kv, prefix: str) -> dict[str, str]:
    """Return {param_name: param_key} for all set params visible under prefix+profile."""
    profile_params_prefix = prefix + "params."
    global_params_prefix = "params."

    result: dict[str, str] = {}

    # Profile-scoped params stored under profiles.<name>.params.*
    for k in kv.list_keys(prefix=profile_params_prefix):
        name = k[len(profile_params_prefix):]
        if name in _ALLOWED_PARAMS and name not in _GLOBAL_PARAMS:
            result[name] = k

    # Global-scoped params stored under params.*
    for k in kv.list_keys(prefix=global_params_prefix):
        name = k[len(global_params_prefix):]
        if name in _GLOBAL_PARAMS:
            result[name] = k

    return result


@cli.group()
def param(): ...


@param.command("list")
@click.option(
    "--available",
    is_flag=True,
    default=False,
    help="List all available params with their types and descriptions.",
)
def sub_cmd_list(available):
    if available:
        current_ns = None
        for name in sorted(_REGISTRY):
            spec = _REGISTRY[name]
            ns = _param_ns(name)
            if ns != current_ns:
                current_ns = ns
                label = _NS_LABELS.get(ns, ns)
                click.echo("")
                click.echo(colored(f"-- {label} --", "yellow"))
            click.echo("")
            click.echo(colored(name, "blue") + f"  ({spec.display_type()})")
            for line in spec.description.splitlines():
                click.echo(f"  {line}")
        return

    click.echo("")
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = None
        try:
            profile = require_active_profile(kv)
        except SystemExit:
            pass  # No active profile — still show global params below
        prefix = _kv_prefix(profile) if profile else ""
        set_params = _list_set_params(kv, prefix)

        has_profile_params = any(
            name not in _GLOBAL_PARAMS for name in set_params
        )
        has_global_params = any(
            name in _GLOBAL_PARAMS for name in set_params
        )

        if not set_params:
            click.echo(f"No params set.")
            return

        scope_parts = []
        if has_profile_params:
            scope_parts.append(f"profile: {profile}")
        if has_global_params:
            scope_parts.append("global")
        click.echo(f"({', '.join(scope_parts)})")

        sorted_names = sorted(set_params)
        for i, name in enumerate(sorted_names):
            key = set_params[name]
            val = kv.get_value(key)
            print(f"""
{colored(name, 'blue')}:

{json.dumps(val, indent=2)}
""".strip() + ("\n\n" if i < len(sorted_names) - 1 else ""))


@param.command(name="set")
@click.argument("name", type=str)
@click.argument("value", type=str)
def sub_cmd_set(name, value):
    """Set a generation parameter."""
    typed_value = _parse_and_validate(name, value)
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        spec = _REGISTRY[name]
        if spec.scope == "global":
            key = _param_storage_key(name)  # params.<name>
        else:
            profile = require_active_profile(kv)
            prefix = _kv_prefix(profile)
            key = _param_storage_key(name, profile_prefix=prefix)  # profiles.<name>.params.<name>
        kv.set_value(key, typed_value)
        conn.commit()
    if spec.scope == "global":
        click.echo(f"Set {name} = {typed_value}  (global)")
    else:
        click.echo(f"Set {name} = {typed_value}  (profile: {profile})")


@param.command(name="show")
def sub_cmd_show():
    """Show all currently set generation parameters."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = None
        try:
            profile = require_active_profile(kv)
        except SystemExit:
            pass  # No active profile — still show global params below
        prefix = _kv_prefix(profile) if profile else ""
        set_params = _list_set_params(kv, prefix)

        if not set_params:
            click.echo(f"No params set.")
            return

        for name in sorted(set_params):
            key = set_params[name]
            val = kv.get_value(key)
            click.echo(f"{name} = {val}")

    has_profile_params = any(
        name not in _GLOBAL_PARAMS for name in set_params
    )
    has_global_params = any(
        name in _GLOBAL_PARAMS for name in set_params
    )
    scope_parts = []
    if has_profile_params:
        scope_parts.append(f"profile: {profile}")
    if has_global_params:
        scope_parts.append("global")
    click.echo(f"({', '.join(scope_parts)})")


@param.command(name="unset")
@click.argument("name", type=str)
def sub_cmd_unset(name):
    """Remove a generation parameter."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        spec = _REGISTRY[name]
        if spec.scope == "global":
            key = _param_storage_key(name)
        else:
            profile = require_active_profile(kv)
            prefix = _kv_prefix(profile)
            key = _param_storage_key(name, profile_prefix=prefix)

        if not kv.exists(key):
            profile_display = "global" if spec.scope == "global" else f"profile: {profile}"
            click.echo(f"{name} is not set.  ({profile_display})")
            return
        kv.delete_value(key)
        conn.commit()
    profile_display = "global" if spec.scope == "global" else f"profile: {profile}"
    click.echo(f"Unset {name}  ({profile_display})")


@param.command(name="manual")
def sub_cmd_manual():
    """Print documentation for every available parameter."""
    for i, name in enumerate(sorted(_REGISTRY)):
        spec = _REGISTRY[name]
        if i:
            click.echo("")
        click.echo(colored(name, "blue") + f"  ({spec.display_type()})")
        for line in spec.description.splitlines():
            click.echo(f"  {line}")