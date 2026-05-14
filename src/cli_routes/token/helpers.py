from typing import Optional
import click


def mask_token(token_value: str) -> str:
    if not token_value:
        return "(empty)"
    return f"{token_value[:2]}...{token_value[-2:]}"


def resolve_token(cursor, provider: str, token_name: str, yes: bool) -> Optional[str]:
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
