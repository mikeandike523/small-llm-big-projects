from __future__ import annotations

import webbrowser

import click

from src.cli_obj import cli
from src.utils.server_state import read_state


@cli.group()
def ui():
    """Commands for the web-based UI."""
    ...


@ui.command(name="open")
def ui_open():
    """Open the UI in the default web browser.

    Reads the port assigned by `slbp server run` from .slbp-server.json.
    Run `slbp server run` first.
    """
    state = read_state()
    if state is None:
        raise click.ClickException(
            ".slbp-server.json not found. Start the server with `slbp server run` first."
        )
    ui_port = state.get("ui_port")
    if not ui_port:
        raise click.ClickException(
            ".slbp-server.json is missing 'ui_port'. Re-run `slbp server run`."
        )
    url = f"http://localhost:{ui_port}"
    click.echo(f"[slbp] Opening {url}")
    webbrowser.open(url, new=0, autoraise=True)
