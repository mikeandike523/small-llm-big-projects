from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager


def _mask_token(token_value: str) -> str:
    if not token_value:
        return "(empty)"
    return f"{token_value[:2]}...{token_value[-2:]}"


def _resolve_token(cursor, provider: str, token_name: str, yes: bool) -> Optional[str]:
    """
    Try to resolve a (provider, token_name) pair to a confirmed token_name.

    - Exact match found -> return token_name as-is.
    - No match, but exactly 1 token exists for provider -> prompt (or auto-accept with yes).
    - No match and 0 tokens for provider -> print error, return None.
    - No match and 2+ tokens for provider -> print error, return None.
    """
    cursor.execute(
        """
        SELECT token_name
        FROM tokens
        WHERE BINARY provider = BINARY %s
          AND BINARY token_name = BINARY %s
        LIMIT 1
        """,
        (provider, token_name),
    )
    if cursor.fetchone() is not None:
        return token_name

    # Exact match not found — check how many tokens exist for this provider.
    cursor.execute(
        "SELECT token_name FROM tokens WHERE BINARY provider = BINARY %s",
        (provider,),
    )
    rows = cursor.fetchall()

    if not rows:
        click.echo(
            f'No tokens found for provider "{provider}". '
            'Use "slbp token list" to see available tokens.'
        )
        return None

    if len(rows) == 1:
        (only_name,) = rows[0]
        display = f'"{only_name}"' if only_name else "(no name)"
        if yes or click.confirm(
            f'Token {display} is the only token for provider "{provider}". Use it?',
            default=True,
        ):
            return only_name
        return None

    # 2+ tokens for provider
    requested_display = f'"{token_name}"' if token_name else "(no name)"
    click.echo(
        f'Token {requested_display} not found for provider "{provider}". '
        'Multiple tokens exist — use "slbp token list" to see available tokens.'
    )
    return None


@cli.group()
def token():
    ...

@token.command(name="list")
def sub_cmd_list():
    """
    List the tokens currently stored, including provider, optional name, and endpoint URL.
    Token value is shown securely as the first 2 and last 2 characters, with ellipses in between.

    If you have a desperate need to recover the token for another purpose
    use "slbp token export -p <provider> -n <name> -o <>" to export to a plaintext file
    (TODO: implement the export command)
    """

    pool = get_pool()

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT provider, token_name, endpoint_url, token_value FROM tokens")
            rows = cursor.fetchall()
            print(f"{'Provider':<20} {'Name':<20} {'Endpoint URL':<40} {'Token Value'}")
            print("-" * 100)
            for provider, token_name, endpoint_url, token_value in rows:
                print(
                    f"{provider:<20} {token_name or '(no name)':<20} "
                    f"{endpoint_url:<40} {_mask_token(token_value)}"
                )


@token.command(name="set")
@click.option(
    "--name", "-n", type=str, required=False, default="",
    help="Optional name of the token to store"
)
@click.option(
    "--endpoint", "-e", type=str, required=False, default=None,
    help="""\
Override the known endpoint in our system for a known provider,
or set the endpoint for an unknown provider.

For instance, our system might already know the current public endpoint
of "openai", but if you want to use a different endpoint, you can specify it here
"""
)
@click.argument("provider", required=True, type=str, nargs=1)
@click.argument("token", required=True, type=str, nargs=1)
def sub_cmd_set(
    name: str,
    endpoint: Optional[str],
    provider: str,
    token: str
):
    """
    Usage: slbp token set [OPTIONS] PROVIDER TOKEN

    Add a token for a given provider.

    Optionally, add a name for the token.

    The (case-sensitive) token name and provider pair is a unique item in the
    database. Calling set with the same name and provider but a different value
    will update the stored token value.

    Examples:

    slbp token set openai <token_value>
    slbp token set -n token1 anthropic <token_value>
    """

    pool = get_pool()
    token_name = name or ""

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            # Step 1: resolve this provider in known_providers using BINARY so matching
            # is case-sensitive even though table collation is case-insensitive.
            cursor.execute(
                """
                SELECT provider_key, display_name, default_endpoint_url
                FROM known_providers
                WHERE BINARY provider_key = BINARY %s
                LIMIT 1
                """,
                (provider,),
            )
            known_provider = cursor.fetchone()

            # Step 2: choose the endpoint to store on the token, and optionally update
            # known_providers so future tokens resolve to the same endpoint.
            chosen_endpoint = endpoint

            if known_provider is None:
                if endpoint is None:
                    warnings.warn(
                        "Provider is not in known_providers and no endpoint was given. "
                        "This token may not be usable until an endpoint is configured. "
                        'Use "slbp endpoint --help" and "slbp endpoint list".'
                    )
                else:
                    # Unknown provider + explicit endpoint: create a known_providers entry
                    # so future calls can reuse this endpoint by provider key alone.
                    cursor.execute(
                        """
                        INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)
                        VALUES (%s, %s, %s)
                        """,
                        (provider, provider, endpoint),
                    )
            else:
                _, _, default_endpoint_url = known_provider
                if endpoint is None:
                    chosen_endpoint = default_endpoint_url
                    if chosen_endpoint is None:
                        warnings.warn(
                            "Known provider has no default endpoint and no endpoint was provided. "
                            "This token may not be usable until an endpoint is configured. "
                            'Use "slbp endpoint --help" and "slbp endpoint list".'
                        )
                elif default_endpoint_url != endpoint:
                    # Known provider + different endpoint: ask before changing the shared
                    # default endpoint that other tokens may implicitly use.
                    overwrite = click.confirm(
                        f'Known provider "{provider}" currently uses endpoint '
                        f'"{default_endpoint_url}". Overwrite it with "{endpoint}"?',
                        default=False,
                    )
                    if not overwrite:
                        click.echo(
                            "No changes made. If you want to keep both endpoints, use a "
                            "different provider string (for example: openai.custom) "
                            "or a different token name."
                        )
                        return
                    cursor.execute(
                        """
                        UPDATE known_providers
                        SET default_endpoint_url = %s
                        WHERE BINARY provider_key = BINARY %s
                        """,
                        (endpoint, provider),
                    )

            # Step 3: find an existing token by (provider, token_name) with case-sensitive
            # matching.
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
                token_id, existing_endpoint, existing_value = existing_token
                if existing_endpoint == chosen_endpoint and existing_value == token:
                    click.echo("Token already exists with the same value and endpoint. No changes made.")
                    return

                # Existing token pair found: ask before replacing the stored token value.
                replace = click.confirm(
                    f'Token for provider "{provider}" and name "{token_name}" exists. Replace it?',
                    default=False,
                )
                if not replace:
                    click.echo("No changes made.")
                    return

                cursor.execute(
                    """
                    UPDATE tokens
                    SET endpoint_url = %s, token_value = %s
                    WHERE id = %s
                    """,
                    (chosen_endpoint, token, token_id),
                )
                conn.commit()
                click.echo("Token updated.")
                return

            # No matching token row exists for (provider, token_name), so create one.
            cursor.execute(
                """
                INSERT INTO tokens (provider, endpoint_url, token_name, token_value)
                VALUES (%s, %s, %s, %s)
                """,
                (provider, chosen_endpoint, token_name, token),
            )
            conn.commit()
            click.echo("Token added.")
            click.echo("""\
Note: token not immediately used (set as active).
If you want to use the token, run

slbp token use <provider> [name]
(name is optional)
""".strip())


@token.command(name="use")
@click.option("-y", "--yes", is_flag=True, help="Auto-accept single-token suggestion without prompting")
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
            KVManager(conn).delete_value("active_token")
            conn.commit()
        click.echo("Active token cleared.")
        return

    token_name = name or ""

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            resolved_name = _resolve_token(cursor, provider, token_name, yes)

        if resolved_name is None:
            return

        KVManager(conn).set_value("active_token", {
            "provider": provider,
            "name": resolved_name,
        })
        conn.commit()

    display = f'"{resolved_name}"' if resolved_name else "(no name)"
    click.echo(f'Active token set to provider="{provider}" name={display}.')


@token.command(name="remove")
@click.option("-y", "--yes", is_flag=True, help="Auto-accept single-token suggestion without prompting")
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
            resolved_name = _resolve_token(cursor, provider, token_name, yes)

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
            if not click.confirm("Clear the active token and proceed with removal?", default=False):
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
    click.echo(f'Token {old_display} for provider "{provider}" renamed to {new_display}.')


@token.command(name="show")
def sub_cmd_show():
    """
    Show the currently active token (provider, name, endpoint, masked value).
    """

    pool = get_pool()

    with pool.get_connection() as conn:
        kv = KVManager(conn)
        active_token = kv.get_value("active_token")

        if not active_token:
            click.echo("No token currently active.")
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
            "was not found in the database. It may have been removed."
        )
        return

    token_value, endpoint_url = row
    name_display = token_name if token_name else "(no name)"
    click.echo(f"{'Provider':<20} {provider}")
    click.echo(f"{'Name':<20} {name_display}")
    click.echo(f"{'Endpoint URL':<20} {endpoint_url or '(none)'}")
    click.echo(f"{'Token Value':<20} {_mask_token(token_value)}")
