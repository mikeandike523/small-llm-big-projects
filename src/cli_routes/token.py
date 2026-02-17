from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool

@cli.group()
def token():
    ...

@token.command(name="list")
def sub_cmd_list():
    """
    List the tokens currently stored, including provider, optional name, and endpoint URL.
    Token value is showns securely as the first 2 and last 2 characters, with ellipses in between
    If you have a desparate need to recover the token for another purpose
    Use "slbp token export -p <provider> -n <name> -o <>" to export to a plaintext file
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
                display_token = f"{token_value[:2]}...{token_value[-2:]}" if token_value else "(empty)"
                print(f"{provider:<20} {token_name or '(no name)':<20} {endpoint_url:<40} {display_token}")


@token.command(name="set")
@click.option(
    "--name", "-n", type=Optional[str], required=False, default=None,
    help="Optional name of the token to store"
)
@click.option(
    "--endpoint", "-e", type=Optional[str], required=False, default=None,
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
    name: Optional[str],
    endpoint: Optional[str],
    provider: str,
    token: str
):
    """
    Usage: slbp token [OPTIONS] PROVIDER TOKEN
    
    Add a token for a given provider.

    Optionally, add a name of the token

    the (case sensitive) token name and provider pair
    is a unique item in the database, 
    calling token with the same name and provider, but with a different value,
    will update the token value in the database

    examples:

    slbp token openai <token_value>
    slbp token -n token1 anthropic <token_value>

    """

    pool = get_pool()

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
            # matching and explicit NULL handling for unnamed tokens.
            cursor.execute(
                """
                SELECT id, endpoint_url, token_value
                FROM tokens
                WHERE BINARY provider = BINARY %s
                  AND (
                    (%s IS NULL AND token_name IS NULL)
                    OR (%s IS NOT NULL AND BINARY token_name = BINARY %s)
                  )
                LIMIT 1
                """,
                (provider, name, name, name),
            )
            existing_token = cursor.fetchone()

            if existing_token is not None:
                token_id, existing_endpoint, existing_value = existing_token
                if existing_endpoint == chosen_endpoint and existing_value == token:
                    click.echo("Token already exists with the same value and endpoint. No changes made.")
                    return

                # Existing token pair found: ask before replacing the stored token value.
                replace = click.confirm(
                    f'Token for provider "{provider}" and name "{name}" exists. Replace it?',
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
                (provider, chosen_endpoint, name, token),
            )
            conn.commit()
            click.echo("Token added.")



