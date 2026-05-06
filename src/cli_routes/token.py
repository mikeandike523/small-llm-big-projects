from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix


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
Set the endpoint URL for this token. Stored directly on the token row.
If the provider is not yet in known_providers, it is added there as a
convenience default (never overwrites an existing known_providers entry).
Omit this flag to leave the per-token endpoint unchanged (or NULL for new
tokens), in which case the endpoint is resolved from known_providers at
connect time.
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

            if existing_value == token and (endpoint is None or endpoint == existing_endpoint):
                click.echo("Token already exists with the same value and endpoint. No changes made.")
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
                    f"with endpoint set to \"{endpoint}\"."
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
            f"  slbp token use {provider}"
            + (f" {token_name}" if token_name else "")
        )


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
            resolved_name = _resolve_token(cursor, provider, token_name, yes)

        if resolved_name is None:
            return

        kv.set_value(prefix + "active_token", {
            "provider": provider,
            "name": resolved_name,
        })
        conn.commit()

    display = f'"{resolved_name}"' if resolved_name else "(no name)"
    click.echo(f'Active token set to provider="{provider}" name={display}.  (profile: {profile})')


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
    click.echo(f"{'Token Value':<20} {_mask_token(token_value)}")
