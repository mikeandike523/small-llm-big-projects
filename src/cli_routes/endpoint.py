from src.cli_obj import cli

from src.data import get_pool

@cli.group()
def endpoint():
    ...

@endpoint.command(name="list")
def sub_cmd_list():
    """
    List or modify known providers and endpoints
    """

    pool = get_pool()

    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT provider_key, display_name, default_endpoint_url FROM known_providers")
            rows = cursor.fetchall()
            print(f"{'Provider Key':<20} {'Display Name':<30} {'Default Endpoint URL'}")
            print("-" * 80)
            for provider_key, display_name, default_endpoint_url in rows:
                print(f"{provider_key:<20} {display_name:<30} {default_endpoint_url}")
    


