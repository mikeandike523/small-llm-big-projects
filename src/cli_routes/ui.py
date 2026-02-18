from __future__ import annotations

import os
from pathlib import Path

import click

from src.cli_obj import cli
from src.utils.process import ManagedProcess, find_bash, run_processes

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UI_DIR = PROJECT_ROOT / "ui"


@cli.group()
def ui():
    """Commands for the web-based UI."""
    ...


@ui.command(name="run")
def ui_run():
    """
    Start the web UI: launches the Vite dev server and the Flask/SocketIO
    backend concurrently, forwarding both streams to stdout.

    Prerequisites:
      - pnpm install has been run inside the ui/ directory
      - Docker Compose services (MySQL, Redis) are running
      - .env exists at the project root (copy from .env.example)
    """
    bash = find_bash()

    print(bash)

    processes = [
        ManagedProcess(
            label="vite",
            cmd=[bash, "-l", "run_ui_server.sh"],
            cwd=PROJECT_ROOT,
        ),
        ManagedProcess(
            label="flask",
            cmd=[bash, "-l", str(PROJECT_ROOT / "run_ui_connector.sh")],
            cwd=os.getcwd(),
        ),
    ]

    click.echo("[slbp] Starting UI processes. Press Ctrl+C to stop.")

    try:
        run_processes(processes)
    except KeyboardInterrupt:
        click.echo("[slbp] Stopped.")
