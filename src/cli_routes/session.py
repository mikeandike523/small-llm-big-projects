from __future__ import annotations

import os
import webbrowser

import click
import httpx

from src.cli_obj import cli
from src.data import get_pool
from src.utils.server_state import read_state
from src.utils.sql.kv_manager import KVManager


@cli.group()
def session():
    """Commands for managing agentic sessions."""
    ...


@session.command(name="new")
@click.option(
    '--pin-project-memory', default=False, type=bool, show_default=True,
    help=(
        'Pin the default project memory scope to the working directory of this session. '
        'When False, project memory defaults to os.getcwd() at the time of each tool call.'
    ),
)
@click.option(
    '--load-skills', is_flag=True, default=False,
    help='Load custom skills from a skills/ directory in the working directory of this session.',
)
@click.option(
    '--load-tools', is_flag=True, default=False,
    help='Load custom tools from a tools/ directory in the working directory of this session.',
)
@click.option(
    '--load-startup-tool-calls', is_flag=True, default=False,
    help='Execute tool calls from startup_tool_calls.json in the working directory on session start.',
)
@click.option(
    '--cwd', default=None,
    help='Working directory for this session. Defaults to the current directory.',
)
@click.option(
    '--enable-trace-recording', '--etr', is_flag=True, default=False,
    help=(
        'Record every LLM completion (full request payload + response) in memory '
        'for this session. Use the "Save fine-tuning traces" button in the UI to '
        'flush the buffer to disk as an XML file.'
    ),
)
def session_new(pin_project_memory, load_skills, load_tools, load_startup_tool_calls, cwd, enable_trace_recording):
    """
    Create a new agentic session and open it in the default web browser.

    Run from the directory you want the agent to work in, or pass --cwd explicitly.
    Per-session context (working directory, skills, custom tools) is captured here,
    not at server startup.

    Requires `slbp server run` to already be running.
    """
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            val = KVManager(conn).get_value("params.model.irat")
        interim_response_as_thinking = val if val is not None else False
    except Exception as exc:
        raise click.ClickException(f"Failed to load session defaults from database: {exc}")

    state = read_state()
    if state is None:
        raise click.ClickException(
            ".slbp-server.json not found. Start the server with `slbp server run` first."
        )
    flask_port = state.get("flask_port")
    proxy_port = state.get("proxy_port")
    if not flask_port or not proxy_port:
        raise click.ClickException(
            ".slbp-server.json is missing port info. Re-run `slbp server run`."
        )

    session_cwd = os.path.abspath(cwd) if cwd else os.getcwd()

    payload: dict = {
        "initial_cwd": session_cwd,
        "pin_project_memory": pin_project_memory,
        "interim_response_as_thinking": interim_response_as_thinking,
        "record_traces": enable_trace_recording,
    }
    if load_skills:
        payload["skills_path"] = os.path.join(session_cwd, "skills")
    if load_tools:
        payload["custom_tools_path"] = os.path.join(session_cwd, "tools")
    if load_startup_tool_calls:
        payload["startup_tool_calls_path"] = os.path.join(session_cwd, "startup_tool_calls.json")

    try:
        response = httpx.post(
            f"http://localhost:{flask_port}/api/sessions",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        raise click.ClickException(
            f"Could not connect to the server at localhost:{flask_port}. "
            "Is `slbp server run` still running?"
        )
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(
            f"Server returned an error: {exc.response.status_code} — {exc.response.text}"
        )

    session_id = response.json().get("session_id")
    if not session_id:
        raise click.ClickException("Server did not return a session_id.")

    url = f"http://localhost:{proxy_port}/session?sessionId={session_id}"
    click.echo(f"[slbp] Session created: {session_id}")
    click.echo(f"[slbp] CWD: {session_cwd}")
    click.echo(f"[slbp] Opening {url}")
    webbrowser.open(url, new=0, autoraise=True)
