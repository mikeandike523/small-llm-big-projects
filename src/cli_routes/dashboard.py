from __future__ import annotations

import webbrowser

import click

from src.cli_obj import cli
from src.utils.server_state import read_state


@cli.command(name="dashboard")
def dashboard_open():
    """Open the SLBP dashboard in the default web browser."""
    state = read_state()
    if state is None:
        raise click.ClickException(
            ".slbp-server.json not found. Start the server with `slbp server run` first."
        )
    ui_port = state.get("ui_port") or state.get("dashboard_port")
    if not ui_port:
        raise click.ClickException(
            ".slbp-server.json is missing port info. Re-run `slbp server run`."
        )
    url = f"http://localhost:{ui_port}/"
    click.echo(f"[slbp] Opening dashboard: {url}")
    webbrowser.open(url, new=0, autoraise=True)
