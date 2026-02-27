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
@click.option(
    '--load-tools', is_flag=True, default=False,
    help='Load custom tools from a tools/ directory in the current working directory.',
)
@click.option(
    '--pin-project-memory', default=True, type=bool, show_default=True,
    help=(
        'Pin the default project memory scope to the working directory at launch time. '
        'When False, project memory defaults to os.getcwd() at the time of each call.'
    ),
)
@click.option(
    '--tool-tracebacks', is_flag=True, default=False,
    help='When a tool raises an exception, return the full traceback instead of just the error message.',
)
def ui_run(streaming, load_skills, load_tools, pin_project_memory, tool_tracebacks):
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
    if load_tools:
        flask_env["SLBP_LOAD_CUSTOM_TOOLS"] = "1"
    flask_env["SLBP_PIN_PROJECT_MEMORY"] = "1" if pin_project_memory else "0"
    if tool_tracebacks:
        flask_env["SLBP_TOOL_TRACEBACKS"] = "1"

    processes = [
        ManagedProcess(
            label="logging",
            cmd=[bash, "-l", str(PROJECT_ROOT / "run_logging_server.sh")],
            cwd=PROJECT_ROOT,
        ),
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
