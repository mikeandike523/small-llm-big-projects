from __future__ import annotations

import textwrap

import click
from termcolor import colored

from src.cli_obj import cli
from src.utils.process_doctor import find_slbp_processes, kill_process, MatchedProcess

_CMDLINE_DISPLAY_WIDTH = 72


def _build_forest(
    matches: list[MatchedProcess],
) -> list[tuple[MatchedProcess, list]]:
    """Group matches into trees by ppid (only among matched processes).

    A match whose ppid isn't itself a matched process is a root -- e.g. the
    outermost bash.exe of a `slbp server run` chain, whose real parent is
    Electron or a terminal, neither of which we match. Two independent
    "slbp server run" generations (a genuine orphan situation) naturally
    surface as two separate root trees, since neither's outermost process is
    a child of the other's.
    """
    by_pid = {m.pid: m for m in matches}
    children: dict[int, list[MatchedProcess]] = {}
    roots: list[MatchedProcess] = []
    for m in matches:
        if m.ppid is not None and m.ppid in by_pid:
            children.setdefault(m.ppid, []).append(m)
        else:
            roots.append(m)
    for lst in children.values():
        lst.sort(key=lambda m: m.create_time)
    roots.sort(key=lambda m: m.create_time)

    def build(node: MatchedProcess) -> tuple[MatchedProcess, list]:
        return (node, [build(c) for c in children.get(node.pid, [])])

    return [build(r) for r in roots]


def _tree_rows(
    forest: list[tuple[MatchedProcess, list]],
) -> list[tuple[MatchedProcess, str]]:
    """Depth-first flatten into (process, tree-prefixed role label) display order."""
    rows: list[tuple[MatchedProcess, str]] = []

    def walk(nodes: list[tuple[MatchedProcess, list]], prefix: str) -> None:
        for i, (node, kids) in enumerate(nodes):
            is_last = i == len(nodes) - 1
            connector = "└─ " if is_last else "├─ "
            rows.append((node, f"{prefix}{connector}{node.role}"))
            child_prefix = prefix + ("   " if is_last else "│  ")
            walk(kids, child_prefix)

    walk(forest, "")
    return rows


def _print_table(matches: list[MatchedProcess]) -> list[MatchedProcess]:
    """Print the process tree and return the processes in the same order they
    were numbered, so the REPL can index into it directly."""
    if not matches:
        click.echo(colored("No slbp server-stack processes found.", "green"))
        return []

    rows = _tree_rows(_build_forest(matches))
    role_width = max(len(label) for _, label in rows)
    role_width = max(role_width, len("ROLE"))
    row_prefix_blank = f"{'':>3}  {'':<{role_width}}  {'':>7}  {'':>8}  {'':<12}  "

    click.echo(
        colored(
            f"{'#':>3}  {'ROLE':<{role_width}}  {'PID':>7}  {'UPTIME':>8}  "
            f"{'PORTS':<12}  COMMAND",
            "cyan",
        )
    )
    for i, (m, label) in enumerate(rows, start=1):
        ports = ",".join(str(p) for p in m.ports) if m.ports else "-"
        prefix = f"{i:>3}  {label:<{role_width}}  {m.pid:>7}  {m.uptime_str:>8}  {ports:<12}  "
        lines = textwrap.wrap(m.cmdline, width=_CMDLINE_DISPLAY_WIDTH) or [""]
        click.echo(prefix + lines[0])
        for cont in lines[1:]:
            click.echo(row_prefix_blank + cont)

    return [m for m, _ in rows]


@cli.command(name="process-doctor")
def process_doctor():
    """
    Last-resort manual cleanup for orphaned slbp server-stack processes
    (ui/proxy/flask, and the `slbp server run` wrapper chain) that a normal
    "Restart Server" failed to fully kill -- e.g. after a sleep/wake cycle
    leaves a process's recorded pid stale. Lists every live process matching
    a known slbp role as a parent/child tree (by ppid, oldest generation
    first) with its uptime and any port it's listening on, then lets you
    kill one by number or everything at once. Two genuinely independent
    "slbp server run" generations show up as two separate root trees.

    Matches on specific script paths (ui/serve.cjs, proxy-server/index.js,
    run_ui_connector.sh, ui_connector/main.py, the server-run wrapper) --
    never a bare repo-path substring, so unrelated tooling running from the
    same venv (editor language servers, etc.) is never listed. Only ever
    finds/kills processes on this machine; does not touch Docker containers
    or the desktop app itself.
    """
    while True:
        matches = find_slbp_processes()
        ordered = _print_table(matches)
        if not ordered:
            return

        click.echo()
        choice = click.prompt(
            "Enter a number to kill that process, ALL to kill everything listed, "
            "r to refresh, or Enter to quit",
            default="",
            show_default=False,
        ).strip()

        if choice == "":
            return

        if choice.lower() == "r":
            continue

        if choice.upper() == "ALL":
            if not click.confirm(
                colored(f"Kill all {len(ordered)} listed process(es)?", "yellow"),
                default=False,
            ):
                continue
            for m in ordered:
                ok, msg = kill_process(m.pid)
                click.echo(colored(f"✅ {msg}", "green") if ok else colored(f"❌ {msg}", "red"))
            click.echo()
            continue

        if choice.isdigit() and 1 <= int(choice) <= len(ordered):
            target = ordered[int(choice) - 1]
            ok, msg = kill_process(target.pid)
            click.echo(colored(f"✅ {msg}", "green") if ok else colored(f"❌ {msg}", "red"))
            click.echo()
            continue

        click.echo(colored(f"Not a valid choice: {choice!r}", "red"))
