from __future__ import annotations

import time
from collections import deque

import click
from termcolor import colored

from src.utils import scheduled_task as st
from src.utils.server_state import read_state


@click.group(name="task")
def task():
    """Manage the Windows Scheduled Task that runs `slbp server run` at login."""
    ...


def _require_task_exists() -> None:
    if not st.task_exists():
        click.echo(
            colored(
                f"Task '{st.TASK_NAME}' is not registered. "
                "Run 'slbp server task init' first.",
                "yellow",
            )
        )
        raise SystemExit(1)


@task.command(name="init")
def task_init():
    """(Idempotently) register the scheduled task to run the server at login."""
    try:
        st.create_or_update_task()
    except RuntimeError as exc:
        click.echo(colored(f"❌ {exc}", "red"))
        raise SystemExit(1)
    click.echo(
        colored(f"✅ Scheduled task '{st.TASK_NAME}' registered (runs at login).", "green")
    )
    click.echo(f"   Logs: {st.LOG_FILE}")
    click.echo("   Run it now with 'slbp server task start' (no logoff/logon needed).")


@task.command(name="start")
def task_start():
    """Manually trigger the scheduled task to start the server now."""
    _require_task_exists()
    try:
        st.start_task()
    except RuntimeError as exc:
        click.echo(colored(f"❌ {exc}", "red"))
        raise SystemExit(1)
    click.echo(colored(f"✅ Started '{st.TASK_NAME}'.", "green"))
    click.echo("   Tail logs with: slbp server task logs -f")


@task.command(name="restart")
def task_restart():
    """Stop any running instance of the scheduled task, then start it again."""
    _require_task_exists()
    st.end_task()
    time.sleep(1)
    try:
        st.start_task()
    except RuntimeError as exc:
        click.echo(colored(f"❌ {exc}", "red"))
        raise SystemExit(1)
    click.echo(colored(f"✅ Restarted '{st.TASK_NAME}'.", "green"))
    click.echo("   Tail logs with: slbp server task logs -f")


@task.command(name="remove")
def task_remove():
    """Stop and unregister the scheduled task (login autostart is disabled)."""
    _require_task_exists()
    try:
        st.delete_task()
    except RuntimeError as exc:
        click.echo(colored(f"❌ {exc}", "red"))
        raise SystemExit(1)
    click.echo(colored(f"✅ Removed scheduled task '{st.TASK_NAME}'.", "green"))
    click.echo(
        f"   Wrapper script and logs left in place at {st.SUPPORT_DIR} "
        "— delete manually if you don't need them."
    )


@task.command(name="health")
def task_health():
    """Report whether the scheduled task and gateway are up, and on what ports."""
    status = st.task_status()
    if status is None:
        click.echo(colored("Scheduled task: not registered (run 'slbp server task init')", "yellow"))
    else:
        color = "green" if status == "Running" else "yellow"
        click.echo(colored(f"Scheduled task: {status}", color))

    state = read_state()
    if state is None:
        click.echo(
            colored(
                "No .slbp-server.json found — the server hasn't written its port "
                "state (never started, or exited uncleanly).",
                "yellow",
            )
        )
        return

    proxy_port = state.get("proxy_port")
    flask_port = state.get("flask_port")
    ui_port = state.get("ui_port")
    click.echo(f"Ports: proxy={proxy_port}  flask={flask_port}  ui={ui_port}")

    if not proxy_port:
        click.echo(colored("No proxy port recorded — can't probe the gateway.", "yellow"))
        return

    reachable, elapsed_ms = st.check_gateway(proxy_port)
    if reachable:
        click.echo(
            colored(
                f"✅ Gateway reachable at http://127.0.0.1:{proxy_port}/ ({elapsed_ms:.0f}ms)",
                "green",
            )
        )
    else:
        click.echo(
            colored(f"❌ Gateway not reachable at http://127.0.0.1:{proxy_port}/", "red")
        )


@task.command(name="logs")
@click.option(
    "-n", "--lines", default=200, show_default=True,
    help="Number of lines to show from the end of the log.",
)
@click.option(
    "-f", "--follow", is_flag=True, default=False,
    help="Keep printing new lines as they're written (like tail -f).",
)
def task_logs(lines, follow):
    """Show (or follow) the scheduled server task's log file."""
    if not st.LOG_FILE.exists():
        click.echo(f"No log file yet at {st.LOG_FILE}. Has the task run?")
        return

    with open(st.LOG_FILE, "r", errors="replace") as f:
        for line in deque(f, maxlen=lines):
            click.echo(line.rstrip("\n"))

        if not follow:
            return
        try:
            while True:
                line = f.readline()
                if line:
                    click.echo(line.rstrip("\n"))
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
