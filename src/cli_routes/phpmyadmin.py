"""`slbp phpmyadmin` — open phpMyAdmin for the local MySQL database."""

from __future__ import annotations

import webbrowser

import click

from src.cli_obj import cli
from src.utils.docker_compose import get_service_port


@cli.command()
def phpmyadmin():
    """Open phpMyAdmin in your browser (MySQL must be running)."""
    try:
        port = get_service_port("phpmyadmin", 80)
    except RuntimeError as exc:
        raise click.ClickException(
            f"Cannot discover phpMyAdmin port. "
            f"Is the phpmyadmin container running? ({exc})"
        )
    url = f"http://localhost:{port}"
    click.echo(f"Opening phpMyAdmin at {url}")
    webbrowser.open(url)