import click
from termcolor import colored

from src.cli_obj import cli
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.cli import multiline_prompt

@cli.command()
def chat():
    """
    Start a chat with your model of choice.
    """

    # Step 1, get the token from the database

    pool = get_pool()

    token_value, endpoint_url = None, None

    with pool.get_connection() as conn:
        active_token = KVManager(conn).get_value("active_token")
        if not active_token:
            click.echo("No active token set. Use `token use <provider> [name]` first.")
            return

        provider = active_token["provider"]
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

        if not row:
            click.echo(f"Token not found for provider={provider!r}, name={token_name!r}.")
            return

        token_value, endpoint_url = row

    if not token_value:
        click.echo(colored("Could not retrieve token value","red"))
        raise SystemExit(-1)
    if not endpoint_url:
        click.echo(colored("Could not retrieve endpoint url value", "red"))
        raise SystemExit(-1)
    
    print(f"Endpoint url: {endpoint_url}")
    if token_name:
        print(f"Token name: {token_name}")
    print(f"Token value: {token_value[:2] + "..." + token_value[-2:]}")
    
    ml_result = None

    while ml_result is None or ml_result.submitted:
        ml_result = multiline_prompt()
        if ml_result.aborted:
            break
        user_message = ml_result.text
        
    
    click.echo("Bye!")