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
def ui_run(streaming, load_skills, load_tools, pin_project_memory, tool_tracebacks, hotfix_gpt_oss_20b_bad_parser, hotfix_gpt_oss_20b_bad_void_call, hotfix_suite_gpt_oss_20b):
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
    if hotfix_gpt_oss_20b_bad_parser or hotfix_suite_gpt_oss_20b:
        flask_env["SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER"] = "1"
    if hotfix_gpt_oss_20b_bad_void_call or hotfix_suite_gpt_oss_20b:
        flask_env["SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL"] = "1"

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
