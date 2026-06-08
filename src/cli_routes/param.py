import json

import click
from termcolor import colored

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import require_active_profile, _kv_prefix
from src.utils.param_registry import (
    ALLOWED_PARAMS as _ALLOWED_PARAMS,
    REGISTRY as _REGISTRY,
    parse_param_value as _parse_param_value_registry,
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
        profile = require_active_profile(kv)
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        keys = [
            k
            for k in kv.list_keys(prefix=params_prefix)
            if k[len(params_prefix):] in _ALLOWED_PARAMS
        ]
        if not keys:
            click.echo(f"No params set.  (profile: {profile})")
        else:
            click.echo(f"(profile: {profile})")
        for i, key in enumerate(keys):
            is_last = i == len(keys) - 1
            display_key = key[len(params_prefix):]
            val = kv.get_value(key)
            print(f"""
{colored(display_key,'blue')}:

{json.dumps(val, indent=2)}
""".strip() + ("\n\n" if not is_last else ""))


@param.command(name="set")
@click.argument("name", type=str)
@click.argument("value", type=str)
def sub_cmd_set(name, value):
    """Set a generation parameter."""
    typed_value = _parse_and_validate(name, value)
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = require_active_profile(kv)
        prefix = _kv_prefix(profile)
        kv.set_value(f"{prefix}params.{name}", typed_value)
        conn.commit()
    click.echo(f"Set {name} = {typed_value}  (profile: {profile})")


@param.command(name="show")
def sub_cmd_show():
    """Show all currently set generation parameters."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = require_active_profile(kv)
        prefix = _kv_prefix(profile)
        params_prefix = prefix + "params."
        keys = [
            k
            for k in kv.list_keys(prefix=params_prefix)
            if k[len(params_prefix):] in _ALLOWED_PARAMS
        ]
        if not keys:
            click.echo(f"No params set.  (profile: {profile})")
            return
        for key in keys:
            param_name = key[len(params_prefix):]
            val = kv.get_value(key)
            click.echo(f"{param_name} = {val}")
    click.echo(f"(profile: {profile})")


@param.command(name="unset")
@click.argument("name", type=str)
def sub_cmd_unset(name):
    """Remove a generation parameter."""
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = require_active_profile(kv)
        prefix = _kv_prefix(profile)
        if not kv.exists(f"{prefix}params.{name}"):
            click.echo(f"{name} is not set.  (profile: {profile})")
            return
        kv.delete_value(f"{prefix}params.{name}")
        conn.commit()
    click.echo(f"Unset {name}  (profile: {profile})")


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
