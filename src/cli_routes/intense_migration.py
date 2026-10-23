"""`slbp intense-migration`: heavy data migrations that are run by hand.

Unlike the SQL migrations in server/migrations (which `update-prod` applies),
these rewrite derived data for every session, can take a long time on big
databases, and need the server stack stopped. Each is registered by name in
_MIGRATIONS and run with `slbp intense-migration run <name>`.
"""

from __future__ import annotations

import sys
import time

import click
from termcolor import colored

from src.cli_obj import cli


@cli.group(name="intense-migration")
def intense_migration():
    """
    Run heavy, manual data migrations (the server must be stopped first).
    """
    ...


def _refuse_if_server_running() -> None:
    from src.utils.process_doctor import find_slbp_processes

    running = find_slbp_processes()
    if not running:
        return
    click.echo(
        colored(
            "The slbp server stack is running. Stop it first (close the desktop "
            "app, or stop the slbp service); `slbp process-doctor` lists "
            "leftover processes.",
            "red",
        )
    )
    for proc in running:
        click.echo(f"  pid {proc.pid}  {proc.role}")
    sys.exit(1)


def _fill_session_cache(dry_run: bool, session_id: str | None) -> None:
    from src.utils.session_cache_backfill import (
        fill_session_cache,
        list_sessions_to_fill,
    )

    session_ids = [session_id] if session_id else list_sessions_to_fill()
    if not session_ids:
        click.echo(colored("Every session's chat history cache is built.", "green"))
        return
    verb = "Would fill" if dry_run else "Filling"
    click.echo(f"{verb} the chat history cache for {len(session_ids)} session(s).")
    failed = 0
    started = time.monotonic()
    for i, sid in enumerate(session_ids, 1):
        prefix = f"[{i}/{len(session_ids)}] {sid}"
        try:
            result = fill_session_cache(sid, dry_run=dry_run)
        except Exception as exc:
            failed += 1
            click.echo(colored(f"{prefix}: failed, left uncached: {exc}", "red"))
            continue
        if result.skipped:
            failed += 1
            click.echo(colored(f"{prefix}: skipped ({result.skipped})", "yellow"))
            continue
        click.echo(
            f"{prefix}: {result.events} events -> {result.turns} turns, "
            f"{result.subturns} subturns"
        )
    elapsed = time.monotonic() - started
    summary = (
        f"Done in {elapsed:.1f}s. {len(session_ids) - failed} ok, {failed} not filled."
    )
    click.echo(colored(summary, "green" if not failed else "yellow"))
    if failed:
        sys.exit(1)


_MIGRATIONS = {
    "fill-session-cache": (
        _fill_session_cache,
        "Build chat_turn_index / chat_history_cache for sessions created "
        "before migration v18.",
    ),
}


@intense_migration.command(name="list")
def intense_migration_list():
    """List the available intense migrations."""
    for name, (_, description) in _MIGRATIONS.items():
        click.echo(f"{colored(name, 'cyan')}  {description}")


@intense_migration.command(name="status")
def intense_migration_status():
    """Show how much work each intense migration still has."""
    from src.utils.session_cache_backfill import list_sessions_to_fill

    pending = len(list_sessions_to_fill())
    color = "green" if pending == 0 else "yellow"
    click.echo(
        f"{colored('fill-session-cache', 'cyan')}: "
        + colored(f"{pending} session(s) not cached yet", color)
    )


@intense_migration.command(name="run")
@click.argument("name", type=click.Choice(sorted(_MIGRATIONS)))
@click.option(
    "--dry-run",
    is_flag=True,
    help="Read and report what would change, without writing anything.",
)
@click.option(
    "--session",
    "session_id",
    default=None,
    help="Only migrate this session id.",
)
def intense_migration_run(name: str, dry_run: bool, session_id: str | None):
    """Run the intense migration NAME. The server must be stopped."""
    if not dry_run:
        _refuse_if_server_running()
    run, _ = _MIGRATIONS[name]
    run(dry_run, session_id)
