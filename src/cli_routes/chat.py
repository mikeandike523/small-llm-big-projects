import click
from termcolor import colored

from src.cli_obj import cli


@cli.command()
def chat():
    """Start a chat with your model of choice."""
    click.echo(colored("TUI is deprecated, use web GUI. Run: slbp ui run", "yellow"))
