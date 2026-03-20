from __future__ import annotations

from pathlib import Path

import click

from src.cli_obj import cli
from src.utils.process import ManagedProcess, find_bash, run_processes
from src.utils.free_port import find_free_port
from src.utils.server_state import write_state, clear_state

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@cli.group()
def server():
    """Commands for the backend server."""
    ...


@server.command(name="run")
@click.option(
    '--tool-tracebacks', is_flag=True, default=False,
    help='When a tool raises an exception, return the full traceback instead of just the error message.',
)
@click.option(
    '--hotfix-gpt-oss-20b-bad-parser', is_flag=True, default=False,
    help=(
        'Hotfix for OpenRouter models that emit spurious <|channel|> tokens inside tool names. '
        'Strips <|channel|> and everything after it from the tool name; if the remainder is a '
        'valid tool, that tool is used.'
    ),
)
@click.option(
    '--hotfix-gpt-oss-20b-bad-void-call', is_flag=True, default=False,
    help=(
        'Hotfix for OpenRouter models that pass spurious arguments to void tools (tools with no '
        'defined parameters). If a tool has no properties in its DEFINITION, any LLM-provided '
        'arguments are discarded and the tool is called with an empty argument set.'
    ),
)
@click.option(
    '--hotfix-suite-gpt-oss-20b', is_flag=True, default=False,
    help='Enable all gpt-oss-20b hotfixes at once (equivalent to --hotfix-gpt-oss-20b-bad-parser and --hotfix-gpt-oss-20b-bad-void-call).',
)
def server_run(tool_tracebacks, hotfix_gpt_oss_20b_bad_parser, hotfix_gpt_oss_20b_bad_void_call, hotfix_suite_gpt_oss_20b):
    """
    Start the server: launches the logging relay, static UI server, and the
    Flask/SocketIO backend concurrently, forwarding all streams to stdout.

    The server is CWD-agnostic. Per-session context (working directory, skills,
    custom tools, etc.) is configured via `slbp session new`.

    Prerequisites:
      - pnpm install has been run inside the ui/ directory
      - Docker Compose services (MySQL, Redis, Piston) are running
      - .env exists at the project root (copy from .env.example)
    """
    bash = find_bash()

    # Allocate three free ports upfront so all processes know where to connect.
    flask_port = find_free_port()
    ui_port = find_free_port()
    logging_port = find_free_port()

    write_state(flask_port=flask_port, ui_port=ui_port, logging_port=logging_port)
    click.echo(
        f"[slbp] Allocated ports — flask:{flask_port}  ui:{ui_port}  logging:{logging_port}"
    )

    flask_env: dict[str, str] = {
        "FLASK_PORT": str(flask_port),
        "LOGGING_PORT": str(logging_port),
        "CORS_ORIGIN": f"http://localhost:{ui_port}",
    }
    if tool_tracebacks:
        flask_env["SLBP_TOOL_TRACEBACKS"] = "1"
    if hotfix_gpt_oss_20b_bad_parser or hotfix_suite_gpt_oss_20b:
        flask_env["SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER"] = "1"
    if hotfix_gpt_oss_20b_bad_void_call or hotfix_suite_gpt_oss_20b:
        flask_env["SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL"] = "1"

    processes = [
        ManagedProcess(
            label="logging",
            cmd=[bash, "-l", str(PROJECT_ROOT / "run_logging_server.sh")],
            cwd=PROJECT_ROOT,
            env={"LOGGING_PORT": str(logging_port)},
        ),
        ManagedProcess(
            label="ui",
            cmd=["node", str(PROJECT_ROOT / "ui" / "serve.cjs")],
            cwd=PROJECT_ROOT / "ui",
            env={"UI_PORT": str(ui_port), "FLASK_PORT": str(flask_port)},
        ),
        ManagedProcess(
            label="flask",
            cmd=[bash, "-l", str(PROJECT_ROOT / "run_ui_connector.sh")],
            cwd=PROJECT_ROOT,
            env=flask_env,
        ),
    ]

    click.echo("[slbp] Starting server processes. Press Ctrl+C to stop.")
    click.echo("[slbp] Run `slbp session new` to open a new session in your browser.")

    try:
        run_processes(processes)
    except KeyboardInterrupt:
        clear_state()
        click.echo("[slbp] Stopped.")
