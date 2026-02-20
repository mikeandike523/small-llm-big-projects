from typing import Optional

import click

from src.cli_obj import cli
from src.data import get_pool

@cli.group(name="service-token")
def service_token():
    ...

@service_token.command(name="set")
@click.option("-n","--name", required=False, type=str, default='',
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

              """.strip())
@click.argument("provider", type=str, required=True, nargs=1)
@click.argument("value", type=str, required=True, nargs=1)
def sub_cmd_set(name:str, provider:str, value:str):

    pool=get_pool()

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