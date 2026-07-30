import json
import shutil


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

def _echo_param(name, val, typestr, terminal_width):
    """Print a single param line with consistent indentation."""
    name_colored = colored(name, "blue")
    is_numeric_or_bool = isinstance(val, (int, float, bool))
    is_str = isinstance(val, str)

    if is_numeric_or_bool:
        click.echo(f"  {name_colored} ({typestr}): {val}")
    elif is_str:
        has_multiline = "\n" in val or "\r\n" in val
        if has_multiline:
            click.echo(f"  {name_colored} ({typestr}):")
            for line in val.splitlines():
                click.echo(f"    {line}")
        else:
            label_len = len(name) + len(f" ({typestr}): ")
            fits = (label_len + len(val)) <= terminal_width
            if fits:
                click.echo(f"  {name_colored} ({typestr}): {val}")
            else:
                click.echo(f"  {name_colored} ({typestr}):")
                click.echo(f"    {val}")
    else:
        # object / dict
        click.echo(f"  {name_colored} ({typestr}):")
        for line in json.dumps(val, indent=2).splitlines():
            click.echo(f"    {line}")

@cli.group()
def param(): ...


@param.command("list")
def sub_cmd_list():
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
            click.echo("No params set.")
            return

        # Separate by registry scope (registry is the source of truth)
        global_items: dict[str, str] = {}
        profile_items: dict[str, str] = {}
        for name, key in set_params.items():
            spec = _REGISTRY.get(name)
            if spec and spec.scope == "global":
                global_items[name] = key
            else:
                profile_items[name] = key

        terminal_width = shutil.get_terminal_size().columns

        # --- Global Params section ---
        if global_items:
            click.echo(colored("-- Global Params --", "magenta", attrs=["bold"]))
            for name in sorted(global_items):
                key = global_items[name]
                val = kv.get_value(key)
                spec = _REGISTRY.get(name)
                typestr = spec.display_type() if spec else type(val).__name__
                _echo_param(name, val, typestr, terminal_width)
            if profile_items:
                click.echo("")

        # --- Profile Params section ---
        if profile_items:
            label = "Profile Params" if not profile else f"Profile ({profile}) Params"
            click.echo(colored(f"-- {label} --", "magenta", attrs=["bold"]))
            for name in sorted(profile_items):
                key = profile_items[name]
                val = kv.get_value(key)
                spec = _REGISTRY.get(name)
                typestr = spec.display_type() if spec else type(val).__name__
                _echo_param(name, val, typestr, terminal_width)


@param.command(name="set")
@click.argument("name", type=str)
@click.argument("value", type=str)
def sub_cmd_set(name, value):
    """Set a generation parameter."""
    typed_value = _parse_and_validate(name, value)
    spec = _REGISTRY[name]
    pool = get_pool()

    with pool.get_connection() as conn:
        kv = KVManager(conn)

        if spec.scope == "global":
            key = f"params.{name}"
        else:
            profile = require_active_profile(kv)
            key = f"profiles.{profile}.params.{name}"

        kv.set_value(key, typed_value)
        conn.commit()

    scope_label = "global" if spec.scope == "global" else f"profile ({profile})"
    click.echo(f"Set '{name}' = {typed_value}  ({scope_label})")


@param.command(name="unset")
@click.argument("name", type=str)
def sub_cmd_unset(name):
    """Remove a generation parameter."""
    spec = _REGISTRY[name]
    pool = get_pool()

    with pool.get_connection() as conn:
        kv = KVManager(conn)

        if spec.scope == "global":
            key = f"params.{name}"
        else:
            profile = require_active_profile(kv)
            key = f"profiles.{profile}.params.{name}"

        if not kv.exists(key):
            scope_label = "global" if spec.scope == "global" else f"profile ({profile})"
            click.echo(f"'{name}' is not set.  ({scope_label})")
            return

        kv.delete_value(key)
        conn.commit()

    scope_label = "global" if spec.scope == "global" else f"profile ({profile})"
    click.echo(f"Unset '{name}'  ({scope_label})")


@param.command(name="manual")
def sub_cmd_manual():
    """Print documentation for every available parameter."""
    global_params = []
    profile_params = []
    for name in sorted(_REGISTRY):
        spec = _REGISTRY[name]
        if spec.scope == "global":
            global_params.append((name, spec))
        else:
            profile_params.append((name, spec))

    if global_params:
        click.echo(colored("-- Global Params --", "magenta", attrs=["bold"]))
        for i, (name, spec) in enumerate(global_params):
            if i:
                click.echo("")
            click.echo(colored(name, "blue") + f"  ({spec.display_type()})")
            for line in spec.description.splitlines():
                click.echo(f"  {line}")

    if profile_params:
        if global_params:
            click.echo("")
        click.echo(colored("-- Profile Params --", "magenta", attrs=["bold"]))
        for i, (name, spec) in enumerate(profile_params):
            if i:
                click.echo("")
            click.echo(colored(name, "blue") + f"  ({spec.display_type()})")
            for line in spec.description.splitlines():
                click.echo(f"  {line}")
