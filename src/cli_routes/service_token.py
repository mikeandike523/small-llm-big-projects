import sys
from typing import Optional

import click

from src.cli_obj import cli
from src.cli_routes.token.helpers import mask_token
from src.data import get_pool


@cli.group(name="service-token")
def service_token(): ...


@service_token.command(name="set")
@click.option(
    "-n",
    "--name",
    required=False,
    type=str,
    default="",
    help="""
              
Optional token name.

For human use only.

Agents will use the most recently created token for the
given provider.

If you want a separate token for a sub-service in a given provider
Use a dot-delimited provider name instead

E.g. (hypothetical)

google.search
google.answers

etc.

              """.strip(),
)
@click.argument("provider", type=str, required=True, nargs=1)
@click.argument("value", type=str, required=True, nargs=1)
def sub_cmd_set(name: str, provider: str, value: str):

    pool = get_pool()

    sql = """
    INSERT INTO service_tokens (provider, name, value)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE
      value = VALUES(value),
      updated_at = CURRENT_TIMESTAMP
    """

    with pool.get_connection() as conn:
        # depending on your driver, this might be conn.cursor() or conn.cursor(dictionary=True)
        with conn.cursor() as cur:
            cur.execute(sql, (provider, name, value))
        conn.commit()

    click.echo(f"Saved token for provider={provider!r} name={name!r}")


def _resolve_service_token(cursor, provider: str, name: str, yes: bool) -> Optional[str]:
    cursor.execute(
        """
        SELECT name
        FROM service_tokens
        WHERE BINARY provider = BINARY %s
          AND BINARY name = BINARY %s
        LIMIT 1
        """,
        (provider, name),
    )
    if cursor.fetchone() is not None:
        return name

    cursor.execute(
        "SELECT name FROM service_tokens WHERE BINARY provider = BINARY %s",
        (provider,),
    )
    rows = cursor.fetchall()
    if not rows:
        click.echo(
            f'No service tokens found for provider "{provider}". '
            'Use "slbp service-token list" to see available tokens.'
        )
        return None

    if len(rows) == 1:
        (only_name,) = rows[0]
        display = f'"{only_name}"' if only_name else "(no name)"
        if yes or click.confirm(
            f'Service token {display} is the only token for provider "{provider}". Use it?',
            default=True,
        ):
            return only_name
        return None

    requested_display = f'"{name}"' if name else "(no name)"
    click.echo(
        f'Service token {requested_display} not found for provider "{provider}". '
        'Multiple service tokens exist - use "slbp service-token list" to see available tokens.'
    )
    return None


@service_token.command(name="list")
def sub_cmd_list():
    """List the service tokens currently stored."""

    pool = get_pool()

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT provider, name, value FROM service_tokens ORDER BY provider, name"
            )
            rows = cursor.fetchall()
            print(f"{'Provider':<20} {'Name':<20} {'Token Value'}")
            print("-" * 60)
            for provider, name, value in rows:
                print(f"{provider:<20} {name or '(no name)':<20} {mask_token(value)}")


@service_token.command(name="remove")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Auto-accept single-token suggestion without prompting",
)
@click.argument("provider", type=str, required=True, nargs=1)
@click.argument("name", type=str, required=False, nargs=1, default="")
def sub_cmd_remove(yes: bool, provider: str, name: str):
    """Remove a stored service token by provider and optional name."""

    pool = get_pool()
    token_name = name or ""

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            resolved_name = _resolve_service_token(cursor, provider, token_name, yes)
            if resolved_name is None:
                return

            cursor.execute(
                """
                DELETE FROM service_tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY name = BINARY %s
                """,
                (provider, resolved_name),
            )

        conn.commit()

    display = f'"{resolved_name}"' if resolved_name else "(no name)"
    click.echo(f'Service token {display} for provider "{provider}" removed.')


@service_token.command(name="move")
@click.argument("args", type=str, required=False, nargs=-1)
def sub_cmd_move(args: tuple[str, ...]):
    """Move/rename a service token to a different (provider, name).

    \b
    Syntax:
        slbp service-token move PROVIDER NAME .. NEW_PROVIDER NEW_NAME

    \b
    Examples:
        slbp service-token move github "" .. gitlab mytoken
        slbp service-token move github oldname .. github newname
        slbp service-token move github "" .. github newname

    \b
    The ".." separator is required. Empty names must be passed as
    an explicit empty string using quotes ("").
    """

    # Find the ".." separator in the arguments.
    try:
        arrow_idx = args.index("..")
    except ValueError:
        raise click.UsageError(
            'Missing ".." separator. Usage: slbp service-token move '
            "PROVIDER NAME .. NEW_PROVIDER NEW_NAME"
        )

    left = args[:arrow_idx]
    right = args[arrow_idx + 1 :]

    if len(left) != 2:
        raise click.UsageError(
            f"Expected 2 args before \"..\" (PROVIDER NAME), got {len(left)}. "
            "Usage: slbp service-token move PROVIDER NAME .. NEW_PROVIDER NEW_NAME"
        )

    if len(right) != 2:
        raise click.UsageError(
            f"Expected 2 args after \"..\" (NEW_PROVIDER NEW_NAME), got {len(right)}. "
            "Usage: slbp service-token move PROVIDER NAME .. NEW_PROVIDER NEW_NAME"
        )

    old_provider, old_name = left
    new_provider, new_name = right

    old_display = f"{old_provider!r}/{old_name!r}" if old_name else f"{old_provider!r}/\"\""
    new_display = f"{new_provider!r}/{new_name!r}" if new_name else f"{new_provider!r}/\"\""

    pool = get_pool()

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            # Check that the source token exists.
            cursor.execute(
                """
                SELECT id, value FROM service_tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY name = BINARY %s
                LIMIT 1
                """,
                (old_provider, old_name),
            )
            row = cursor.fetchone()

            if row is None:
                click.echo(
                    f'Service token {old_display} not found. '
                    'Use "slbp service-token list" to see available tokens.'
                )
                return

            token_id, value = row

            # If source == destination, nothing to do.
            if old_provider == new_provider and old_name == new_name:
                click.echo(
                    f"Source and destination are the same ({old_display}). No changes made."
                )
                return

            # Check for destination conflict.
            cursor.execute(
                """
                SELECT 1 FROM service_tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY name = BINARY %s
                LIMIT 1
                """,
                (new_provider, new_name),
            )
            if cursor.fetchone() is not None:
                click.echo(
                    f'Destination {new_display} already exists. '
                    "Remove it first or choose a different destination."
                )
                return

            # Perform the move: update provider and name in-place.
            cursor.execute(
                """
                UPDATE service_tokens
                SET provider = %s, name = %s
                WHERE id = %s
                """,
                (new_provider, new_name, token_id),
            )

        conn.commit()

    click.echo(
        f"Service token moved from {old_display} to {new_display}."
    )
