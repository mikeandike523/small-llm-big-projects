import click

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager

_ALLOWED_PARAMS = {"temperature", "top_p", "top_k","max_tokens"}


def _parse_and_validate(name: str, raw_value: str):
    """Parse and validate a param value. Returns the typed value or raises click.BadParameter."""
    if name not in _ALLOWED_PARAMS:
        raise click.BadParameter(
            f"Unknown param '{name}'. Allowed: {', '.join(sorted(_ALLOWED_PARAMS))}",
            param_hint="name",
        )
    try:
        if name == "top_k":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("top_k must be > 0", param_hint="value")
            return value
        elif name == "max_tokens":
            value = int(raw_value)
            if value <= 0:
                raise click.BadParameter("max_tokens must be > 0", param_hint="value")
            return value
        else:
            value = float(raw_value)
            if name == "temperature" and not (0.0 <= value <= 2.0):
                raise click.BadParameter("temperature must be between 0.0 and 2.0", param_hint="value")
            if name == "top_p" and not (0.0 <= value <= 1.0):
                raise click.BadParameter("top_p must be between 0.0 and 1.0", param_hint="value")
            return value
    except ValueError:
        type_hint = "integer" if name == "top_k" else "float"
        raise click.BadParameter(f"value for '{name}' must be a {type_hint}", param_hint="value")


@cli.group()
def params():
    ...


@params.command(name="set")
@click.argument("name", type=str)
@click.argument("value", type=str)
def sub_cmd_set(name, value):
    """
    Set a generation parameter (temperature, top_p, top_k).
    """
    typed_value = _parse_and_validate(name, value)
    pool = get_pool()
    with pool.get_connection() as conn:
        KVManager(conn).set_value(f"params.{name}", typed_value)
        conn.commit()
    click.echo(f"Set params.{name} = {typed_value}")


@params.command(name="show")
def sub_cmd_show():
    """
    Show all currently set generation parameters.
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        keys = kv.list_keys(prefix="params.")
        if not keys:
            click.echo("No params set.")
            return
        for key in keys:
            param_name = key[len("params."):]
            val = kv.get_value(key)
            click.echo(f"{param_name} = {val}")


@params.command(name="unset")
@click.argument("name", type=str)
def sub_cmd_unset(name):
    """
    Remove a generation parameter.
    """
    if name not in _ALLOWED_PARAMS:
        raise click.BadParameter(
            f"Unknown param '{name}'. Allowed: {', '.join(sorted(_ALLOWED_PARAMS))}",
            param_hint="name",
        )
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        if not kv.exists(f"params.{name}"):
            click.echo(f"params.{name} is not set.")
            return
        kv.delete_value(f"params.{name}")
        conn.commit()
    click.echo(f"Unset params.{name}")
