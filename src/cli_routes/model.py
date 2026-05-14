import click

from src.data import get_pool
from src.cli_obj import cli
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix


@cli.group()
def model(): ...


@model.command(name="use")
@click.argument("model_name", type=str, required=False)
def sub_cmd_use(model_name):
    """
    Sets the active model by name
    """

    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        kv.set_value(prefix + "model", model_name)
        conn.commit()
    click.echo(
        f"Set current model to: {model_name or '(not set)'}  (profile: {profile})"
    )


@model.command(name="show")
def sub_cmd_show():
    """
    Show the current model name
    """
    pool = get_pool()
    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        model_name = kv.get_value(prefix + "model") or None
    click.echo(f"Current model name: {model_name or '(not set)'}  (profile: {profile})")
