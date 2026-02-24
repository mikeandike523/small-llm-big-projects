from __future__ import annotations

import os
import webbrowser
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
@click.option(
    '--streaming', default=True, type=bool, show_default=True,
    help='Stream tokens from the LLM. Set false to receive the full response at once (useful for diagnosing vLLM garbled-character bugs).',
)
@click.option(
    '--load-skills', is_flag=True, default=False,
    help='Load custom skills from a skills/ directory in the current working directory.',
)
def ui_run(streaming, load_skills):
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

    flask_env = {}
    if not streaming:
        flask_env["SLBP_STREAMING"] = "0"
    if load_skills:
        flask_env["SLBP_LOAD_SKILLS"] = "1"

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
            env=flask_env if flask_env else None,
        ),
    ]

    click.echo("[slbp] Starting UI processes. Press Ctrl+C to stop.")

    ui_port = os.environ.get("UI_PORT", "5173")
    webbrowser.open(f"http://localhost:{ui_port}", new=0, autoraise=True)

    try:
        run_processes(processes)
    except KeyboardInterrupt:
        click.echo("[slbp] Stopped.")
