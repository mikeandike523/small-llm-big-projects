from __future__ import annotations

import click
from termcolor import colored

from src.cli_obj import cli
from src.utils.app_launcher import install_start_menu_shortcut


@cli.group()
def desktop():
    """Commands for the SLBP desktop app."""
    ...


@desktop.command(name="install")
def desktop_install():
    """(Idempotently) add a Start Menu shortcut for the SLBP desktop app."""
    try:
        shortcut_path = install_start_menu_shortcut()
    except RuntimeError as exc:
        click.echo(colored(f"❌ {exc}", "red"))
        raise SystemExit(1)
    click.echo(colored(f"✅ Start Menu shortcut created: {shortcut_path}", "green"))
    click.echo("   Find it in the Start Menu under 'SLBP'.")
