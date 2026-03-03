import os
import subprocess
import tempfile
from pathlib import Path
from typing import Union


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,  # git diff returns 1 when differences exist; that's normal
    )


def git_heuristic_is_binary(path: Union[str, os.PathLike]) -> bool:
    """
    Cross-platform heuristic-only binary detection using Git's own diff logic.

    Works outside a git repo (uses `git diff --no-index`).
    Does NOT respect .gitattributes (because that's repo-specific policy).

    Returns:
        True  -> Git considers it binary
        False -> Git considers it text
    """
    p = Path(path)

    if not p.is_file():
        raise FileNotFoundError(str(p))

    # Create an empty file as the left side of the diff (portable replacement for /dev/null)
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as tmp:
        empty_path = tmp.name

    try:
        proc = _run_git([
            "diff",
            "--no-index",
            "--numstat",
            "--no-ext-diff",
            "--",
            empty_path,
            str(p),
        ])

        out = proc.stdout.strip()

        # If Git can't produce numstat output for some reason, be conservative:
        # fall back to a simple NUL-byte sniff (still reasonable).
        if not out:
            with p.open("rb") as f:
                chunk = f.read(8000)
            return b"\x00" in chunk

        # numstat line looks like: "<ins>\t<del>\t<path>"
        # For binary: "-\t-\t<path>"
        first_line = out.splitlines()[0]
        cols = first_line.split("\t")
        if len(cols) >= 2 and cols[0] == "-" and cols[1] == "-":
            return True
        return False

    finally:
        try:
            os.remove(empty_path)
        except OSError:
            pass