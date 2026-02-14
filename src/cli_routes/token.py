import click

from ..cli_obj import cli


@cli.command()
@click.option(
    "--name", "-n", required=False, default=None,
    help="Optional name of the token to store"
)
@click.option(
    "--endpoint", "-e", required=False, default=None,
    help="""\
Override the known endpoint in our system for a known provider,
or set the endpoint for an unknown provider.

For instance, our system might already know the current public endpoint
of "openai", but if you want to use a different endpoint, you can specify it here
"""
)
@click.argument("provider", required=True, type=str, nargs=1)
@click.argument("token", required=True, type=str, nargs=1)
def token():
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
