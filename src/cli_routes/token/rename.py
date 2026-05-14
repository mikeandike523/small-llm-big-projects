from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.cli_routes.token.helpers import mask_token, resolve_token

from src.cli_routes.token_obj import token


@token.command(name="rename")
@click.argument("provider", type=str, required=True, nargs=1)
@click.argument("old_name", type=str, required=True, nargs=1)
@click.argument("new_name", type=str, required=True, nargs=1)
def sub_cmd_rename(provider: str, old_name: str, new_name: str):
    """
    Rename a stored token (change its name) for a given provider.

    All three arguments are required. To refer to a token that has no name,
    pass an explicit empty string using quotes:

    \b
        slbp token rename openai "" my-new-name   # rename the unnamed token
        slbp token rename openai old-name ""       # remove the name (make unnamed)
        slbp token rename openai old-name new-name # rename to a different name

    \b
    Rules:
      - Exact match only: no auto-suggestion is performed.
      - The (provider, new_name) pair must not already exist in the database.
      - If the renamed token is currently active, the active-token record is
        updated automatically to reflect the new name.
    """

    pool = get_pool()

    with pool.get_connection() as conn:
        kv = KVManager(conn)

        with conn.cursor() as cursor:
            # Exact lookup — no suggestion fallback.
            cursor.execute(
                """
                SELECT id FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, old_name),
            )
            existing = cursor.fetchone()

            if existing is None:
                old_display = f'"{old_name}"' if old_name else "(no name)"
                click.echo(
                    f'Token {old_display} for provider "{provider}" not found. '
                    'Use "slbp token list" to see available tokens.'
                )
                return

            token_id = existing[0]

            # Ensure the target name is not already taken.
            cursor.execute(
                """
                SELECT 1 FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, new_name),
            )
            if cursor.fetchone() is not None:
                new_display = f'"{new_name}"' if new_name else "(no name)"
                click.echo(
                    f'A token named {new_display} already exists for provider "{provider}". '
                    "Choose a different name or remove the existing token first."
                )
                return

            cursor.execute(
                "UPDATE tokens SET token_name = %s WHERE id = %s",
                (new_name, token_id),
            )

        # If this token is currently active, keep the KV record in sync.
        active_token = kv.get_value("active_token")
        if (
            active_token is not None
            and active_token.get("provider") == provider
            and active_token.get("name", "") == old_name
        ):
            kv.set_value("active_token", {"provider": provider, "name": new_name})

        conn.commit()

    old_display = f'"{old_name}"' if old_name else "(no name)"
    new_display = f'"{new_name}"' if new_name else "(no name)"
    click.echo(
        f'Token {old_display} for provider "{provider}" renamed to {new_display}.'
    )
