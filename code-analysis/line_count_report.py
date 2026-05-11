#!/usr/bin/env python3
"""Line-count report for all Git-tracked text files.

Commands:
  top [N]          Top N files by line count (default 20).
  over [N]         Files exceeding N lines (default 500).
  counts / lc      Full list sorted descending.
  total            Sum only.
  max              Single largest file.
  files            List tracked source files only.

An optional .lcrignore file (sibling of this script) may contain fnmatch-style
glob patterns (one per line, # for comments) to exclude files from the report.
Patterns are matched against each file's POSIX-style path relative to the repo root.

Usage examples:
  python code-analysis/line_count_report.py over
  python code-analysis/line_count_report.py over 300
  python code-analysis/line_count_report.py top 30
"""

import os
import subprocess
import sys
from pathlib import Path

import click
from tqdm import tqdm


THRESHOLD_DEFAULT = 500
_SCRIPT_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def repo_root() -> Path:
    result = _git("rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        raise click.ClickException("Not inside a git repository.")
    return Path(result.stdout.decode().strip())


def _git_worktree_files() -> list[Path]:
    click.echo("Listing git-tracked files...", err=True)
    out = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    files = [Path(p.decode()) for p in out.split(b"\0") if p]
    click.echo(f"  {len(files)} tracked file(s) found.", err=True)
    return files


def _diff_attr_value(path: Path) -> str:
    out = _git("check-attr", "-z", "diff", "--", str(path)).stdout
    parts = [p.decode(errors="replace") for p in out.split(b"\0") if p]
    return parts[2] if len(parts) >= 3 else "unspecified"


def _diff_engine_sees_text(path: Path) -> bool:
    proc = _git(
        "diff", "--no-index", "--numstat", "--",
        os.devnull,
        str(path),
        check=False,
    )
    line = proc.stdout.decode(errors="replace").splitlines()
    if not line:
        return False
    fields = line[0].split("\t", 2)
    if len(fields) < 2:
        return False
    added, deleted = fields[0], fields[1]
    return added != "-" and deleted != "-"


def _is_sourceish(path: Path) -> bool:
    if not path.is_file():
        return False
    attr = _diff_attr_value(path)
    if attr in {"unset", "false"}:
        return False
    if attr == "unspecified":
        return _diff_engine_sees_text(path)
    return True


# ---------------------------------------------------------------------------
# .lcrignore
# ---------------------------------------------------------------------------

def load_ignore_patterns() -> list[str]:
    ignore_file = _SCRIPT_DIR / ".lcrignore"
    if not ignore_file.exists():
        return []
    patterns = [
        line.strip()
        for line in ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if patterns:
        click.echo(
            f"  Loaded {len(patterns)} ignore pattern(s) from .lcrignore.", err=True
        )
    return patterns


def _is_ignored(path: Path, patterns: list[str]) -> bool:
    for pat in patterns:
        # Path.match() supports ** properly (Python 3.12+).
        # Bare names like "pnpm-lock.yaml" (no slashes) also match at any depth.
        if path.match(pat):
            return True
    return False


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def sourceish_files(ignore_patterns: list[str]) -> list[Path]:
    all_files = _git_worktree_files()

    if ignore_patterns:
        candidates = []
        for path in all_files:
            if _is_ignored(path, ignore_patterns):
                click.echo(f"[Ignored] {path}", err=True)
            else:
                candidates.append(path)
    else:
        candidates = all_files

    click.echo(f"Filtering {len(candidates)} file(s) for text source content...", err=True)
    result: list[Path] = []
    for path in tqdm(candidates, desc="Filtering", unit="file", file=sys.stderr):
        if _is_sourceish(path):
            result.append(path)
    click.echo(f"  {len(result)} source file(s) to analyze.", err=True)
    return result


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def file_counts(ignore_patterns: list[str]) -> list[tuple[int, Path]]:
    src = sourceish_files(ignore_patterns)
    click.echo(f"Counting lines in {len(src)} file(s)...", err=True)
    rows: list[tuple[int, Path]] = []
    for path in tqdm(src, desc="Counting ", unit="file", file=sys.stderr):
        rows.append((_line_count(path), path))
    return sorted(rows, reverse=True)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_rows(rows: list[tuple[int, Path]], threshold: int | None = None) -> None:
    for n, path in rows:
        marker = "  ***" if threshold and n > threshold else ""
        click.echo(f"{n:8d}  {path}{marker}")


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Line-count report for all Git-tracked text files."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(over)


def _setup() -> list[str]:
    """Change to repo root and return ignore patterns. Called at the start of each command."""
    root = repo_root()
    os.chdir(root)
    return load_ignore_patterns()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@cli.command()
def files() -> None:
    """List all tracked source files (no line counts)."""
    ignore = _setup()
    for path in sourceish_files(ignore):
        click.echo(path)


@cli.command()
@click.argument("n", type=click.IntRange(min=1), default=20, metavar="N")
def top(n: int) -> None:
    """Top N files by line count (default 20)."""
    ignore = _setup()
    rows = file_counts(ignore)
    print_rows(rows[:n], threshold=THRESHOLD_DEFAULT)


@cli.command()
@click.argument("threshold", type=click.IntRange(min=0), default=THRESHOLD_DEFAULT, metavar="THRESHOLD")
def over(threshold: int) -> None:
    """Files exceeding THRESHOLD lines (default 500)."""
    ignore = _setup()
    rows = file_counts(ignore)
    over_rows = [(n, p) for n, p in rows if n > threshold]
    if not over_rows:
        click.echo(f"No files exceed {threshold} lines.")
        return
    click.echo(f"Files with > {threshold} lines  ({len(over_rows)} found):\n")
    print_rows(over_rows)
    click.echo(f"\n{len(over_rows)} file(s) over {threshold} lines.")


@cli.command(name="counts")
def cmd_counts() -> None:
    """Full list sorted descending with total."""
    ignore = _setup()
    rows = file_counts(ignore)
    print_rows(rows, threshold=THRESHOLD_DEFAULT)
    click.echo(f"\n{sum(n for n, _ in rows):8d}  total")


@cli.command(name="lc")
def cmd_lc() -> None:
    """Alias for counts."""
    ignore = _setup()
    rows = file_counts(ignore)
    print_rows(rows, threshold=THRESHOLD_DEFAULT)
    click.echo(f"\n{sum(n for n, _ in rows):8d}  total")


@cli.command()
def total() -> None:
    """Print total line count only."""
    ignore = _setup()
    rows = file_counts(ignore)
    click.echo(sum(n for n, _ in rows))


@cli.command(name="max")
def cmd_max() -> None:
    """Print the single largest file."""
    ignore = _setup()
    rows = file_counts(ignore)
    if rows:
        n, path = rows[0]
        click.echo(f"{n}\t{path}")


if __name__ == "__main__":
    cli()
