from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.cli_routes.token.helpers import mask_token, resolve_token

from src.cli_routes.token_obj import token


@token.command(name="show")
def sub_cmd_show():
    """
    Show the currently active token (provider, name, endpoint, masked value).
    """

    pool = get_pool()

    with pool.get_connection() as conn:
        kv = KVManager(conn)
        profile = get_active_profile(kv)
        prefix = _kv_prefix(profile)
        active_token = kv.get_value(prefix + "active_token")

        if not active_token:
            click.echo(f"No token currently active.  (profile: {profile})")
            return

        provider = active_token.get("provider", "")
        token_name = active_token.get("name", "")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_value, endpoint_url
                FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, token_name),
            )
            row = cursor.fetchone()

    if row is None:
        click.echo(
            f'Active token (provider="{provider}", name="{token_name}") '
            f"was not found in the database. It may have been removed.  (profile: {profile})"
        )
        return

    token_value, endpoint_url = row
    name_display = token_name if token_name else "(no name)"
    click.echo(f"{'Profile':<20} {profile}")
    click.echo(f"{'Provider':<20} {provider}")
    click.echo(f"{'Name':<20} {name_display}")
    click.echo(f"{'Endpoint URL':<20} {endpoint_url or '(none)'}")
    click.echo(f"{'Token Value':<20} {mask_token(token_value)}")
