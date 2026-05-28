from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

from src.cli_routes.token.helpers import mask_token, resolve_token

from src.cli_routes.token_obj import token

@token.command(name="remove")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Auto-accept single-token suggestion without prompting",
)
@click.argument("provider", type=str, required=True, nargs=1)
@click.argument("name", type=str, required=False, nargs=1, default="")
def sub_cmd_remove(yes: bool, provider: str, name: str):
    """
    Remove a stored token by provider and optional name.

    If the token being removed is currently active, you will be prompted
    to clear the active token first.
    """

    pool = get_pool()
    token_name = name or ""

    with pool.get_connection() as conn:
        kv = KVManager(conn)

        with conn.cursor() as cursor:
            resolved_name = resolve_token(cursor, provider, token_name, yes)

        if resolved_name is None:
            return

        # Check whether the resolved token is currently active.
        active_token = kv.get_value("active_token")
        is_active = (
            active_token is not None
            and active_token.get("provider") == provider
            and active_token.get("name", "") == resolved_name
        )

        if is_active:
            display = f'"{resolved_name}"' if resolved_name else "(no name)"
            click.echo(
                f'Warning: token {display} for provider "{provider}" is currently active.'
            )
            if not click.confirm(
                "Clear the active token and proceed with removal?", default=False
            ):
                click.echo("Aborted. No changes made.")
                return
            kv.delete_value("active_token")

        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                """,
                (provider, resolved_name),
            )

        conn.commit()

    display = f'"{resolved_name}"' if resolved_name else "(no name)"
    click.echo(f'Token {display} for provider "{provider}" removed.')
