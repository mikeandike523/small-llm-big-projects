from __future__ import annotations

import click
from termcolor import colored

from src.cli_obj import cli
from src.utils.app_launcher import (
    icon_changed_since_last_install,
    install_start_menu_shortcut,
    restart_explorer,
)


@cli.group()
def desktop():
    """Commands for the SLBP desktop app."""
    ...


@desktop.command(name="install")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Auto-accept the Explorer restart prompt if the icon changed, without prompting.",
)
def desktop_install(yes: bool):
    """(Idempotently) add a Start Menu shortcut for the SLBP desktop app."""
    try:
        shortcut_path = install_start_menu_shortcut()
    except RuntimeError as exc:
        click.echo(colored(f"❌ {exc}", "red"))
        raise SystemExit(1)
    click.echo(colored(f"✅ Start Menu shortcut created: {shortcut_path}", "green"))
    click.echo("   Find it in the Start Menu under 'SLBP'.")

    if icon_changed_since_last_install():
        if yes or click.confirm(
            "Icon changed since the last install — Windows may still show the old "
            "one in the Start Menu/taskbar until Explorer restarts. Restart it now?",
            default=False,
        ):
            restart_explorer()
            click.echo(colored("✅ Restarted Explorer.", "green"))
