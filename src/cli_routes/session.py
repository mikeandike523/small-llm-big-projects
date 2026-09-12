from __future__ import annotations

import os

import click
import httpx

from src.cli_obj import cli
from src.data import get_pool
from src.utils.app_launcher import open_session
from src.utils.server_state import read_state
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, require_active_profile, _kv_prefix
from src.utils.approval_modes import APPROVAL_MODE_DEFAULT, APPROVAL_MODES


@cli.group()
def session():
    """Commands for managing agentic sessions."""
    ...


@session.command(name="new")
@click.option(
    "--load-skills/--no-load-skills",
    default=True,
    help="Load custom skills from a skills/ directory in the working directory of this session. (default: on)",
)
@click.option(
    "--load-tools/--no-load-tools",
    default=True,
    help="Load custom tools from a tools/ directory in the working directory of this session. (default: on)",
)
@click.option(
    "--load-startup-tool-calls/--no-load-startup-tool-calls",
    default=True,
    help="Execute tool calls from startup_tool_calls.json in the working directory on session start. (default: on)",
)
@click.option(
    "--cwd",
    default=None,
    help="Working directory for this session. Defaults to the current directory.",
)
@click.option(
    "--starting-profile",
    default=None,
    help=(
        "Profile to use for this session. "
        "Defaults to the system default profile set via 'slbp profile use'."
    ),
)
@click.option(
    "--approval-mode",
    type=click.Choice(APPROVAL_MODES, case_sensitive=False),
    default=APPROVAL_MODE_DEFAULT,
    help="Approval mode for this session.",
)
def session_new(
    load_skills,
    load_tools,
    load_startup_tool_calls,
    cwd,
    starting_profile,
    approval_mode,
):
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
            kv = KVManager(conn)
            # Validate --starting-profile if given; otherwise require the default profile.
            if starting_profile:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM profiles WHERE name = %s LIMIT 1",
                        (starting_profile,),
                    )
                    if cur.fetchone() is None:
                        raise click.ClickException(
                            f"Profile '{starting_profile}' does not exist. "
                            "Use 'slbp profile list' to see available profiles."
                        )
                effective_profile = starting_profile
            else:
                effective_profile = require_active_profile(kv)
            prefix = _kv_prefix(effective_profile)
            val = kv.get_value(f"{prefix}params.model.irat")
        interim_response_as_thinking = val if val is not None else False
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(
            f"Failed to load session defaults from database: {exc}"
        )

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
    approval_mode = approval_mode.lower()

    payload: dict = {
        "initial_cwd": session_cwd,
        "interim_response_as_thinking": interim_response_as_thinking,
        "profile_name": starting_profile,
        "approval_mode": approval_mode,
    }
    if load_skills:
        payload["skills_path"] = os.path.join(session_cwd, "skills")
    if load_tools:
        payload["custom_tools_path"] = os.path.join(session_cwd, "tools")
    if load_startup_tool_calls:
        payload["startup_tool_calls_path"] = os.path.join(
            session_cwd, "startup_tool_calls.json"
        )

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

    click.echo(f"[slbp] Session created: {session_id}")
    click.echo(f"[slbp] Profile: {starting_profile or effective_profile}")
    click.echo(f"[slbp] Approval mode: {approval_mode}")
    click.echo(f"[slbp] CWD: {session_cwd}")
    open_session(session_id, proxy_port)
