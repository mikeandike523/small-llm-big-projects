from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.cli_routes.token.helpers import mask_token, resolve_token

from src.cli_routes.token_obj import token



@token.command(name="use")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Auto-accept single-token suggestion without prompting",
)
@click.argument("provider", type=str, required=True, nargs=1)
@click.argument("name", type=str, required=False, nargs=1, default="")
def sub_cmd_use(yes: bool, provider: str, name: str):
    """
    Set the active token by provider and optional name.

    Use "none" as the provider to clear the active token (logout):

        slbp token use none
    """

    pool = get_pool()

    if provider.lower() == "none":
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            profile = get_active_profile(kv)
            prefix = _kv_prefix(profile)
            kv.delete_value(prefix + "active_token")
            conn.commit()
        click.echo(f"Active token cleared.  (profile: {profile})")
        return

    token_name = name or ""

    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        with conn.cursor() as cursor:
            resolved_name = resolve_token(cursor, provider, token_name, yes)

        if resolved_name is None:
            return

        kv.set_value(
            prefix + "active_token",
            {
                "provider": provider,
                "name": resolved_name,
            },
        )
        conn.commit()

    display = f'"{resolved_name}"' if resolved_name else "(no name)"
    click.echo(
        f'Active token set to provider="{provider}" name={display}.  (profile: {profile})'
    )
