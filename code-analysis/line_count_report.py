#!/usr/bin/env python3
"""
Line-count report for all Git-tracked text files.

Commands:
  top [N]          top N files by line count (default 20)
  over [N]         files exceeding N lines (default 500)
  counts / lc      full list sorted descending
  total            sum only
  max              single largest file
  files            list tracked source files only

Usage examples:
  python code-analysis/line_count_report.py over
  python code-analysis/line_count_report.py over 300
  python code-analysis/line_count_report.py top 30
"""

import argparse
import os
import subprocess
from pathlib import Path
from typing import Iterable


THRESHOLD_DEFAULT = 500


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel").stdout.decode().strip())


def git_worktree_files() -> list[Path]:
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    return [Path(p.decode()) for p in out.split(b"\0") if p]


def git_diff_attr_value(path: Path) -> str:
    out = git("check-attr", "-z", "diff", "--", str(path)).stdout
    parts = [p.decode(errors="replace") for p in out.split(b"\0") if p]
    return parts[2] if len(parts) >= 3 else "unspecified"


def git_diff_engine_sees_text(path: Path) -> bool:
    proc = git(
        "diff", "--no-index", "--numstat", "--",
        os.devnull,   # works as /dev/null on Windows too
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


def is_git_sourceish(path: Path) -> bool:
    if not path.is_file():
        return False
    attr = git_diff_attr_value(path)
    if attr in {"unset", "false"}:
        return False
    if attr == "unspecified":
        return git_diff_engine_sees_text(path)
    return True


def sourceish_files() -> Iterable[Path]:
    for path in git_worktree_files():
        if is_git_sourceish(path):
            yield path


def line_count(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def counts() -> list[tuple[int, Path]]:
    return sorted(
        [(line_count(path), path) for path in sourceish_files()],
        reverse=True,
    )


def print_rows(rows: list[tuple[int, Path]], threshold: int | None = None) -> None:
    for n, path in rows:
        marker = "  ***" if threshold and n > threshold else ""
        print(f"{n:8d}  {path}{marker}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("files")
    sub.add_parser("counts")
    sub.add_parser("lc")
    sub.add_parser("total")
    sub.add_parser("max")

    top_p = sub.add_parser("top")
    top_p.add_argument("n", type=int, nargs="?", default=20)

    over_p = sub.add_parser("over")
    over_p.add_argument("threshold", type=int, nargs="?", default=THRESHOLD_DEFAULT)

    args = parser.parse_args()

    root = repo_root()
    os.chdir(root)

    cmd = args.cmd or "over"

    if cmd == "files":
        for path in sourceish_files():
            print(path)
        return

    all_rows = counts()

    if cmd == "over":
        threshold = args.threshold
        over = [(n, p) for n, p in all_rows if n > threshold]
        if not over:
            print(f"No files exceed {threshold} lines.")
            return
        print(f"Files with > {threshold} lines  ({len(over)} found):\n")
        print_rows(over)
        print(f"\n{len(over)} file(s) over {threshold} lines.")

    elif cmd == "top":
        print_rows(all_rows[: args.n], threshold=THRESHOLD_DEFAULT)

    elif cmd in {"counts", "lc"}:
        print_rows(all_rows, threshold=THRESHOLD_DEFAULT)
        print(f"\n{sum(n for n, _ in all_rows):8d}  total")

    elif cmd == "total":
        print(sum(n for n, _ in all_rows))

    elif cmd == "max":
        if all_rows:
            n, path = all_rows[0]
            print(f"{n}\t{path}")

    else:
        parser.error(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
