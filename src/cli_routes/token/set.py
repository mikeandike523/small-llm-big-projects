from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager

from src.cli_routes.token.helpers import mask_token, resolve_token

from src.cli_routes.token_obj import token



@token.command(name="set")
@click.option(
    "--name",
    "-n",
    type=str,
    required=False,
    default="",
    help="Optional name of the token to store",
)
@click.option(
    "--endpoint",
    "-e",
    type=str,
    required=False,
    default=None,
    help="""\
Set the endpoint URL for this token. Stored directly on the token row.
If the provider is not yet in known_providers, it is added there as a
convenience default (never overwrites an existing known_providers entry).
Omit this flag to leave the per-token endpoint unchanged (or NULL for new
tokens), in which case the endpoint is resolved from known_providers at
connect time.
""",
)
@click.argument("provider", required=True, type=str, nargs=1)
@click.argument("token", required=True, type=str, nargs=1)
def sub_cmd_set(name: str, endpoint: Optional[str], provider: str, token: str):
    """
    Usage: slbp token set [OPTIONS] PROVIDER TOKEN

    Add or rotate a token for a given provider.

    The (provider, name) pair uniquely identifies a token. Calling set on an
    existing pair rotates the token value. With --endpoint the per-token
    endpoint is also updated; without it the existing endpoint is left as-is.

    If no --endpoint is given, the endpoint is resolved from known_providers
    at connect time. An error will surface in the UI if neither the token row
    nor known_providers has an endpoint configured.

    Examples:

    slbp token set openai <token_value>
    slbp token set -n token1 anthropic <token_value>
    slbp token set -e https://my.proxy/v1 openai <token_value>
    """

    pool = get_pool()
    token_name = name or ""
    name_display = f'"{token_name}"' if token_name else "(no name)"

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            # Look up existing token row.
            cursor.execute(
                """
                SELECT id, endpoint_url, token_value
                FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND BINARY token_name = BINARY %s
                LIMIT 1
                """,
                (provider, token_name),
            )
            existing_token = cursor.fetchone()

        if existing_token is not None:
            # ── Rotation path ──────────────────────────────────────────────
            token_id, existing_endpoint, existing_value = existing_token

            if existing_value == token and (
                endpoint is None or endpoint == existing_endpoint
            ):
                click.echo(
                    "Token already exists with the same value and endpoint. No changes made."
                )
                return

            replace = click.confirm(
                f'Token for provider "{provider}" name {name_display} already exists. Rotate it?',
                default=False,
            )
            if not replace:
                click.echo("No changes made.")
                return

            if endpoint is not None:
                # Update the token row with the new value AND new endpoint.
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE tokens SET token_value = %s, endpoint_url = %s WHERE id = %s",
                        (token, endpoint, token_id),
                    )
                click.echo(
                    f'Token for provider "{provider}" name {name_display} rotated to new value '
                    f'with endpoint set to "{endpoint}".'
                )
                # Add to known_providers if not present (never overwrite).
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM known_providers WHERE BINARY provider_key = BINARY %s LIMIT 1",
                        (provider,),
                    )
                    if cursor.fetchone() is None:
                        cursor.execute(
                            """
                            INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)
                            VALUES (%s, %s, %s)
                            """,
                            (provider, provider, endpoint),
                        )
                        click.echo(
                            f'Provider "{provider}" was not in known_providers — '
                            f'added with default endpoint "{endpoint}".'
                        )
            else:
                # Update token value only; leave endpoint_url untouched.
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE tokens SET token_value = %s WHERE id = %s",
                        (token, token_id),
                    )
                click.echo(
                    f'Token for provider "{provider}" name {name_display} rotated to new value. '
                    f"Endpoint unchanged."
                )

            conn.commit()
            return

        # ── First-time / new token path ────────────────────────────────────
        if endpoint is not None:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tokens (provider, endpoint_url, token_name, token_value)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (provider, endpoint, token_name, token),
                )
            click.echo(
                f'Token added for provider "{provider}" name {name_display} '
                f'with endpoint "{endpoint}".'
            )
            # Add to known_providers if not present (never overwrite).
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM known_providers WHERE BINARY provider_key = BINARY %s LIMIT 1",
                    (provider,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        """
                        INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)
                        VALUES (%s, %s, %s)
                        """,
                        (provider, provider, endpoint),
                    )
                    click.echo(
                        f'Provider "{provider}" was not in known_providers — '
                        f'added with default endpoint "{endpoint}".'
                    )
        else:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tokens (provider, endpoint_url, token_name, token_value)
                    VALUES (%s, NULL, %s, %s)
                    """,
                    (provider, token_name, token),
                )
            click.echo(f'Token added for provider "{provider}" name {name_display}.')
            # Warn if no endpoint will be resolvable at connect time.
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT default_endpoint_url FROM known_providers
                    WHERE BINARY provider_key = BINARY %s LIMIT 1
                    """,
                    (provider,),
                )
                kp_row = cursor.fetchone()
            if not kp_row or not kp_row[0]:
                warnings.warn(
                    f'No endpoint configured for provider "{provider}" and none found in '
                    f"known_providers. This token will not be usable until an endpoint is set. "
                    f'Run "slbp endpoint --help" or re-run set with --endpoint.'
                )

        conn.commit()
        click.echo(
            "Note: token is not yet active. To use it, run:\n"
            f"  slbp token use {provider}" + (f" {token_name}" if token_name else "")
        )

