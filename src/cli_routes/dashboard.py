from __future__ import annotations

import click

from src.cli_obj import cli
from src.utils.app_launcher import open_dashboard
from src.utils.server_state import read_state


@cli.command(name="dashboard")
def dashboard_open():
    """Open the SLBP dashboard in the desktop app."""
    state = read_state()
    if state is None:
        raise click.ClickException(
            ".slbp-server.json not found. Start the server with `slbp server run` first."
        )
    proxy_port = state.get("proxy_port")
    if not proxy_port:
        raise click.ClickException(
            ".slbp-server.json is missing port info. Re-run `slbp server run`."
        )
    click.echo("[slbp] Opening dashboard")
    open_dashboard(proxy_port)
