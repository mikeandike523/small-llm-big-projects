from __future__ import annotations

import os

import click
import httpx

from src.cli_obj import cli
from src.data import get_pool
from src.utils.app_launcher import open_session, open_session_in_browser
from src.utils.server_state import read_state
from src.utils.sql.kv_manager import KVManager
from src.utils.param_helper import get_param_value
from src.utils.profile_utils import (
    get_active_profile,
    require_active_profile,
    _kv_prefix,
)
from src.utils.approval_modes import APPROVAL_MODE_DEFAULT, APPROVAL_MODES


def _post_new_session(flask_port: int, payload: dict) -> httpx.Response:
    try:
        return httpx.post(
            f"http://localhost:{flask_port}/api/sessions",
            json=payload,
            timeout=10,
        )
    except httpx.ConnectError:
        raise click.ClickException(
            f"Could not connect to the server at localhost:{flask_port}. "
            "Is `slbp server run` still running?"
        )


def _is_privileged_cwd_response(response: httpx.Response) -> bool:
    if response.status_code != 409:
        return False
    try:
        return response.json().get("code") == "privileged_cwd"
    except ValueError:
        return False


@cli.group()
def session():
    """Commands for managing agentic sessions."""
    ...


@session.command(name="new")
@click.option(
    "--load-custom-skills-tools/--no-load-custom-skills-tools",
    default=True,
    help=(
        "Load custom skills and tools from the skills/ and tools/ directories "
        "in this session's working directory. (default: on)"
    ),
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
@click.option(
    "--browser",
    is_flag=True,
    help="Open the session in the default web browser instead of the desktop app.",
)
@click.option(
    "--allow-privileged-cwd",
    is_flag=True,
    help=(
        "Accept a working directory the server flags as privileged or not "
        "recommended (e.g. your home folder itself, /etc) without asking."
    ),
)
def session_new(
    load_custom_skills_tools,
    load_startup_tool_calls,
    cwd,
    starting_profile,
    approval_mode,
    browser,
    allow_privileged_cwd,
):
    """
    Create a new agentic session and open it in the SLBP desktop app.

    Run from the directory you want the agent to work in, or pass --cwd explicitly.
    Per-session context (working directory, skills, custom tools) is captured here,
    not at server startup. Pass --browser to use the default web browser instead.

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
            interim_response_as_thinking = get_param_value(
                kv, "model.irat", profile_prefix=prefix
            )
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
        "load_custom_skills_tools": load_custom_skills_tools,
    }
    if load_startup_tool_calls:
        payload["startup_tool_calls_path"] = os.path.join(
            session_cwd, "startup_tool_calls.json"
        )

    if allow_privileged_cwd:
        payload["allow_privileged_cwd"] = True
    response = _post_new_session(flask_port, payload)
    if _is_privileged_cwd_response(response):
        body = response.json()
        click.echo(
            click.style(
                f"Warning: {body.get('error')} ({body.get('reason')})", fg="yellow"
            )
        )
        if not click.confirm("Proceed with caution?", default=False):
            raise click.ClickException(
                "Session not created. Choose another folder with --cwd, or pass "
                "--allow-privileged-cwd."
            )
        payload["allow_privileged_cwd"] = True
        response = _post_new_session(flask_port, payload)
    if response.is_error:
        raise click.ClickException(
            f"Server returned an error: {response.status_code} — {response.text}"
        )

    session_id = response.json().get("session_id")
    if not session_id:
        raise click.ClickException("Server did not return a session_id.")

    click.echo(f"[slbp] Session created: {session_id}")
    click.echo(f"[slbp] Profile: {starting_profile or effective_profile}")
    click.echo(f"[slbp] Approval mode: {approval_mode}")
    click.echo(f"[slbp] CWD: {session_cwd}")
    if browser:
        open_session_in_browser(session_id, proxy_port)
    else:
        open_session(session_id, proxy_port)
