from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import click
from termcolor import colored

from src.cli_obj import cli
from src.cli_routes.server_task import task as _task_group
from src.utils.docker_compose import _find_docker_compose, get_service_port
from src.utils.env_info import get_default_workspace_dir
from src.utils.free_port import find_free_port, find_preferred_port
from src.utils.process import ManagedProcess, find_bash, run_processes
from src.utils.server_state import clear_state, get_running_server_state, write_state
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.param_registry import param_storage_key
from src.utils.profile_utils import get_active_profile, _kv_prefix

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DOCKER_SERVICES = [
    ("mysql", 3306),
    ("redis", 6379),
    ("piston", 2000),
]


def _ok(label: str) -> None:
    click.echo(colored(f"  ✅ {label}", "green"))


class _PreflightFailed(Exception):
    """Raised internally by _fail() to short-circuit one preflight attempt."""


def _fail(label: str, detail: str) -> None:
    click.echo(colored(f"  ❌ {label}: {detail}", "red"))
    raise _PreflightFailed()


def _run_preflight_checks_once() -> bool:
    """Run the pre-flight checks once, echoing ✅/❌ per item. Returns True iff all passed."""
    try:
        # 1. docker compose CLI available
        try:
            _find_docker_compose()
            _ok("docker compose available")
        except RuntimeError as exc:
            _fail("docker compose available", str(exc))

        # 2. Docker daemon reachable
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
            if r.returncode != 0:
                _fail(
                    "docker daemon running",
                    "docker info returned non-zero — is Docker Desktop running?",
                )
            _ok("docker daemon running")
        except FileNotFoundError:
            _fail("docker daemon running", "docker not found in PATH")
        except subprocess.TimeoutExpired:
            _fail("docker daemon running", "docker info timed out")

        # 3. Each compose service
        for service, port in _DOCKER_SERVICES:
            try:
                get_service_port(service, port)
                _ok(f"{service} service running (port {port})")
            except Exception as exc:
                _fail(f"{service} service running", str(exc))
    except _PreflightFailed:
        return False
    return True


def _run_preflight_checks(retry_interval: int = 10) -> None:
    """
    Run pre-flight checks (Docker Compose CLI, Docker daemon, each compose
    service), retrying every `retry_interval` seconds -- printing a fresh
    ✅/❌ block on every attempt -- until they all pass.

    Waiting is unconditional rather than opt-in: Docker Desktop is often
    still starting up right after login (e.g. when the desktop app launches
    the server automatically), and failing fast there just means the same
    manual retry every time. Ctrl+C aborts, same as any other point here.
    """
    attempt = 1
    while True:
        click.echo(
            f"[slbp] Pre-flight checks (attempt {attempt}):"
            if attempt > 1
            else "[slbp] Pre-flight checks:"
        )
        if _run_preflight_checks_once():
            return
        click.echo(colored(f"[slbp] Not ready yet — retrying in {retry_interval}s...", "yellow"))
        time.sleep(retry_interval)
        attempt += 1


def _maybe_clear_desktop_log() -> None:
    """Truncate .slbp-server.log if the desktop app requested it via the global param.

    Called only when --desktop was passed. The desktop app opens this file itself
    (append mode) before spawning this process and inherits it as our stdout/stderr,
    so truncating the file's contents here -- rather than deleting/recreating it --
    is what keeps that inherited handle valid: appended writes always land at the
    (now zero) end of file.
    """
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            key = param_storage_key("desktop.slbp-process.clear-logs-on-start")
            enabled = bool(kv.get_value(key, default=False))
    except Exception as exc:
        click.echo(
            colored(f"Warning: could not check clear-logs-on-start param: {exc}", "yellow")
        )
        return
    if not enabled:
        return
    log_path = PROJECT_ROOT / ".slbp-server.log"
    try:
        with open(log_path, "r+b") as f:
            f.truncate(0)
    except FileNotFoundError:
        pass
    except OSError as exc:
        click.echo(colored(f"Warning: could not clear {log_path.name}: {exc}", "yellow"))


@cli.group()
def server():
    """Commands for the backend server."""
    ...


server.add_command(_task_group)


@server.command(name="run")
@click.option(
    "--tool-tracebacks",
    is_flag=True,
    default=False,
    help="When a tool raises an exception, return the full traceback instead of just the error message.",
)
@click.option(
    "--hotfix-gpt-oss-20b-bad-parser",
    is_flag=True,
    default=False,
    help=(
        "Hotfix for OpenRouter models that emit spurious <|channel|> tokens inside tool names. "
        "Strips <|channel|> and everything after it from the tool name; if the remainder is a "
        "valid tool, that tool is used."
    ),
)
@click.option(
    "--hotfix-gpt-oss-20b-bad-void-call",
    is_flag=True,
    default=False,
    help=(
        "Hotfix for OpenRouter models that pass spurious arguments to void tools (tools with no "
        "defined parameters). If a tool has no properties in its DEFINITION, any LLM-provided "
        "arguments are discarded and the tool is called with an empty argument set."
    ),
)
@click.option(
    "--hotfix-suite-gpt-oss-20b",
    is_flag=True,
    default=False,
    help=(
        "Enable all gpt-oss-20b hotfixes at once "
        "(equivalent to --hotfix-gpt-oss-20b-bad-parser and --hotfix-gpt-oss-20b-bad-void-call)."
    ),
)
@click.option(
    "--dashboard-port",
    default=None,
    type=int,
    help="Port for the UI/dashboard server. Defaults to a random free port.",
)
@click.option(
    "--proxy-port",
    default=None,
    type=int,
    help=(
        "Port for the gateway proxy (single public entry point). Defaults to the first free "
        "port from a preferred list (so a restarted server tends to reuse the same entry point), "
        "falling back to a random free port. Useful for VM/containerized deployments where a "
        "fixed entry point is required."
    ),
)
@click.option(
    "--desktop",
    is_flag=True,
    default=False,
    help=(
        "Indicates this process was launched by the desktop app, enabling desktop-only "
        "behaviors (currently: honoring desktop.slbp-process.clear-logs-on-start). Not "
        "meant to be passed when starting the server manually from a terminal."
    ),
)
def server_run(
    tool_tracebacks,
    hotfix_gpt_oss_20b_bad_parser,
    hotfix_gpt_oss_20b_bad_void_call,
    hotfix_suite_gpt_oss_20b,
    dashboard_port,
    proxy_port,
    desktop,
):
    """
    Start the server: launches the static UI server, gateway proxy, and the
    Flask/SocketIO backend concurrently, forwarding all streams to stdout.

    The server is CWD-agnostic. Per-session context (working directory, skills,
    custom tools, etc.) is configured via `slbp session new`.

    Prerequisites:
      - pnpm install has been run inside the ui/ directory
      - Docker Compose services (MySQL, Redis, Piston) are running
      - .env exists at the project root (copy from .env.example)
    """
    running = get_running_server_state()
    if running is not None:
        click.echo(
            colored(
                f"[slbp] Server already running (proxy port {running['proxy_port']}, "
                f"pid {running.get('pid', 'unknown')}). Not starting a new instance.",
                "yellow",
            )
        )
        raise SystemExit(1)

    _run_preflight_checks()

    if desktop:
        _maybe_clear_desktop_log()

    # Lightweight pre-flight config advisory (non-fatal).
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            profile = get_active_profile(kv)
        if profile is None:
            click.echo(
                click.style(
                    "Warning: No default profile selected. "
                    "The server will start, but sessions cannot be created until "
                    "a profile is configured. Visit the dashboard Config page or "
                    "use 'slbp profile new <name>' / 'slbp profile use <name>'.",
                    fg="yellow",
                )
            )
        else:
            with pool.get_connection() as conn:
                kv = KVManager(conn)
                prefix = _kv_prefix(profile)
                active_token = kv.get_value(prefix + "active_token")
                model_val = kv.get_value(prefix + "model")
            if not active_token:
                click.echo(
                    click.style(
                        f"Warning: No active token set for default profile '{profile}'. "
                        "Use 'slbp token use <provider>' to set one.",
                        fg="yellow",
                    )
                )
            elif not model_val:
                click.echo(
                    click.style(
                        "Warning: No model set. The platform may automatically choose a model. "
                        "This is not recommended.",
                        fg="yellow",
                    )
                )
    except Exception as exc:
        click.echo(click.style(f"Warning: Could not verify config: {exc}", fg="yellow"))

    bash = find_bash()
    workspace_dir = get_default_workspace_dir()
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)

    flask_port = find_free_port()
    ui_port = dashboard_port if dashboard_port is not None else find_free_port()
    gw_port = proxy_port if proxy_port is not None else find_preferred_port()

    write_state(flask_port=flask_port, ui_port=ui_port, proxy_port=gw_port)
    click.echo(
        f"[slbp] Allocated ports - proxy:{gw_port}  flask:{flask_port}  ui:{ui_port}"
    )
    click.echo(f"[slbp] Workspace: {workspace_dir}")

    server_cwd = os.getcwd()
    flask_env: dict[str, str] = {
        "FLASK_PORT": str(flask_port),
        "PROXY_PORT": str(gw_port),
        "SLBP_SERVER_CWD": server_cwd,
    }
    if tool_tracebacks:
        flask_env["SLBP_TOOL_TRACEBACKS"] = "1"
    if hotfix_gpt_oss_20b_bad_parser or hotfix_suite_gpt_oss_20b:
        flask_env["SLBP_HOTFIX_GPT_OSS_20B_BAD_PARSER"] = "1"
    if hotfix_gpt_oss_20b_bad_void_call or hotfix_suite_gpt_oss_20b:
        flask_env["SLBP_HOTFIX_GPT_OSS_20B_BAD_VOID_CALL"] = "1"

    processes = [
        ManagedProcess(
            label="ui",
            cmd=["node", str(PROJECT_ROOT / "ui" / "serve.cjs")],
            cwd=PROJECT_ROOT / "ui",
            env={"UI_PORT": str(ui_port)},
        ),
        ManagedProcess(
            label="proxy",
            cmd=["node", str(PROJECT_ROOT / "proxy-server" / "index.js")],
            cwd=PROJECT_ROOT / "proxy-server",
            env={
                "PROXY_PORT": str(gw_port),
                "FLASK_PORT": str(flask_port),
                "UI_PORT": str(ui_port),
            },
        ),
        ManagedProcess(
            label="flask",
            cmd=[bash, "-l", str(PROJECT_ROOT / "run_ui_connector.sh")],
            cwd=PROJECT_ROOT,
            env=flask_env,
        ),
    ]

    click.echo("[slbp] Starting server processes. Press Ctrl+C to stop.")
    click.echo(f"[slbp] Gateway: http://localhost:{gw_port}/")
    click.echo(
        "[slbp] Run `slbp session new` to open a new session, or `slbp dashboard` to open the dashboard."
    )

    try:
        run_processes(processes)
    except KeyboardInterrupt:
        clear_state()
        click.echo("[slbp] Stopped.")
