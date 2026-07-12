from __future__ import annotations

import shutil

import click
from termcolor import colored

from src.utils import scheduled_task as st


@click.group(name="task")
def task():
    """
    Legacy cleanup for the old Windows Scheduled Task that ran `slbp server
    run` at login. That approach has been replaced by the desktop app
    auto-starting the server on launch -- `purge` is the only command left,
    for removing a task registered before that change.
    """
    ...


@task.command(name="purge")
def task_purge():
    """Stop and unregister the old scheduled task, and remove its support files."""
    existed = st.task_exists()

    if existed:
        try:
            st.delete_task()
        except RuntimeError as exc:
            click.echo(colored(f"❌ {exc}", "red"))
            raise SystemExit(1)
        click.echo(colored(f"✅ Removed scheduled task '{st.TASK_NAME}'.", "green"))

    if st.SUPPORT_DIR.exists():
        shutil.rmtree(st.SUPPORT_DIR, ignore_errors=True)
        if st.SUPPORT_DIR.exists():
            click.echo(
                colored(
                    f"❌ Could not fully remove {st.SUPPORT_DIR} — a file inside it is likely "
                    "still open (e.g. a leftover slbp server process still writing to server.log). "
                    "Stop that process and re-run this command.",
                    "red",
                )
            )
            raise SystemExit(1)
        click.echo(colored(f"✅ Removed {st.SUPPORT_DIR}.", "green"))
    elif not existed:
        click.echo("Nothing to purge — no scheduled task or support files found.")
