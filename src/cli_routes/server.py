from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click
from termcolor import colored

from src.cli_obj import cli
from src.utils.docker_compose import _find_docker_compose, get_service_port
from src.utils.env_info import get_default_workspace_dir
from src.utils.free_port import find_free_port
from src.utils.process import ManagedProcess, find_bash, run_processes
from src.utils.server_state import clear_state, write_state
from src.data import get_pool
from src.utils.sql.kv_manager import KVManager
from src.utils.profile_utils import get_active_profile, _kv_prefix

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DOCKER_SERVICES = [
    ("mysql", 3306),
    ("redis", 6379),
    ("piston", 2000),
]


def _ok(label: str) -> None:
    click.echo(colored(f"  ✅ {label}", "green"))


def _fail(label: str, detail: str) -> None:
    click.echo(colored(f"  ❌ {label}: {detail}", "red"))
    raise SystemExit(1)


def _run_preflight_checks() -> None:
    click.echo("[slbp] Pre-flight checks:")

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
            _fail("docker daemon running", "docker info returned non-zero — is Docker Desktop running?")
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


@cli.group()
def server():
    """Commands for the backend server."""
    ...


@server.command(name="run")
@click.option(
    "--tool-tracebacks", is_flag=True, default=False,
    help="When a tool raises an exception, return the full traceback instead of just the error message.",
)
@click.option(
    "--hotfix-gpt-oss-20b-bad-parser", is_flag=True, default=False,
    help=(
        "Hotfix for OpenRouter models that emit spurious <|channel|> tokens inside tool names. "
        "Strips <|channel|> and everything after it from the tool name; if the remainder is a "
        "valid tool, that tool is used."
    ),
)
@click.option(
    "--hotfix-gpt-oss-20b-bad-void-call", is_flag=True, default=False,
    help=(
        "Hotfix for OpenRouter models that pass spurious arguments to void tools (tools with no "
        "defined parameters). If a tool has no properties in its DEFINITION, any LLM-provided "
        "arguments are discarded and the tool is called with an empty argument set."
    ),
)
@click.option(
    "--hotfix-suite-gpt-oss-20b", is_flag=True, default=False,
    help=(
        "Enable all gpt-oss-20b hotfixes at once "
        "(equivalent to --hotfix-gpt-oss-20b-bad-parser and --hotfix-gpt-oss-20b-bad-void-call)."
    ),
)
@click.option(
    "--trace-folder-max-gb", default=None, type=float,
    help=(
        "Maximum size in GB for the .slbp-traces folder. When saving traces would "
        "exceed this limit, oldest trace files are deleted until under the limit. "
        "Defaults to no limit."
    ),
)
@click.option(
    "--dashboard-port", default=None, type=int,
    help="Port for the UI/dashboard server. Defaults to a random free port.",
)
@click.option(
    "--proxy-port", default=None, type=int,
    help=(
        "Port for the gateway proxy (single public entry point). Defaults to a random free port. "
        "Useful for VM/containerized deployments where a fixed entry point is required."
    ),
)
def server_run(
    tool_tracebacks,
    hotfix_gpt_oss_20b_bad_parser,
    hotfix_gpt_oss_20b_bad_void_call,
    hotfix_suite_gpt_oss_20b,
    trace_folder_max_gb,
    dashboard_port,
    proxy_port,
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
    _run_preflight_checks()

    # Lightweight pre-flight config check.
    try:
        pool = get_pool()
        with pool.get_connection() as conn:
            kv = KVManager(conn)
            profile = get_active_profile(kv)
            prefix = _kv_prefix(profile)
            active_token = kv.get_value(prefix + "active_token")
            model_val = kv.get_value(prefix + "model")
        if not active_token:
            click.echo(click.style(
                f"Error: No active token set for profile '{profile}'. "
                "Use 'slbp token use <provider>' to set one.",
                fg="red",
            ))
            raise SystemExit(1)
        if not model_val:
            click.echo(click.style(
                "Warning: No model set. The platform may automatically choose a model. "
                "This is not recommended.",
                fg="yellow",
            ))
    except SystemExit:
        raise
    except Exception as exc:
        click.echo(click.style(f"Warning: Could not verify config: {exc}", fg="yellow"))

    bash = find_bash()
    workspace_dir = get_default_workspace_dir()
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)

    flask_port = find_free_port()
    ui_port = dashboard_port if dashboard_port is not None else find_free_port()
    gw_port = proxy_port if proxy_port is not None else find_free_port()

    write_state(flask_port=flask_port, ui_port=ui_port, proxy_port=gw_port)
    click.echo(f"[slbp] Allocated ports - proxy:{gw_port}  flask:{flask_port}  ui:{ui_port}")
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
    if trace_folder_max_gb is not None:
        flask_env["SLBP_TRACE_FOLDER_MAX_GB"] = str(trace_folder_max_gb)

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
    click.echo("[slbp] Run `slbp session new` to open a new session, or `slbp dashboard` to open the dashboard.")

    try:
        run_processes(processes)
    except KeyboardInterrupt:
        clear_state()
        click.echo("[slbp] Stopped.")
