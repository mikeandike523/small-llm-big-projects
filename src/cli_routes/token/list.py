from typing import Optional
import click
import warnings

from src.cli_obj import cli

from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix
from src.cli_routes.token.helpers import mask_token, resolve_token

from src.cli_routes.token_obj import token

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
            cursor.execute(
                "SELECT provider, token_name, endpoint_url, token_value FROM tokens"
            )
            rows = cursor.fetchall()
            print(f"{'Provider':<20} {'Name':<20} {'Endpoint URL':<40} {'Token Value'}")
            print("-" * 100)
            for provider, token_name, endpoint_url, token_value in rows:
                print(
                    f"{provider:<20} {token_name or '(no name)':<20} "
                    f"{endpoint_url:<40} {mask_token(token_value)}"
                )
