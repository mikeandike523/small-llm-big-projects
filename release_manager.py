#!/usr/bin/env python3
"""Release manager: bump/set versions and record release notes.

Usage:
    release_manager.py bump <ui|backend|desktop> <major|minor|patch> <message...>
    release_manager.py set <ui|backend|desktop> <version> <message...> [--force]

- Bumps semver in the target package.json (root = backend, ui/ = frontend).
  set takes an explicit version (must be greater than the current one,
  unless --force).
- Writes ui/public/ui-release-notes/<VERSION>.txt (message only) and regenerates
  changelog-index.json in the same folder. Backend: ./backend-release-notes/.
  Desktop: ./desktop/desktop-release-notes/.
- Does not touch git.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "ui": {"package": ROOT / "ui" / "package.json", "notes_dir": ROOT / "ui" / "public" / "ui-release-notes"},
    "backend": {"package": ROOT / "package.json", "notes_dir": ROOT / "backend-release-notes"},
    "desktop": {"package": ROOT / "desktop" / "package.json", "notes_dir": ROOT / "desktop" / "desktop-release-notes"},
}
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version(pkg: Path) -> tuple:
    data = json.loads(pkg.read_text(encoding="utf-8"))
    m = SEMVER_RE.match(str(data.get("version", "")))
    if not m:
        sys.exit(f"ERROR: {pkg} has non-semver version {data.get('version')!r}")
    return tuple(int(x) for x in m.groups())


def bump_version(v: tuple, component: str) -> tuple:
    major, minor, patch = v
    if component == "major":
        return (major + 1, 0, 0)
    if component == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_index(notes_dir: Path) -> list:
    idx = notes_dir / "changelog-index.json"
    if not idx.exists():
        return []
    try:
        return json.loads(idx.read_text(encoding="utf-8")).get("releases", [])
    except (json.JSONDecodeError, OSError):
        return []


def rebuild_index(notes_dir: Path, new_entry: dict) -> None:
    """Rebuild index from existing files (dates carried forward) + new entry."""
    entries = [e for e in load_index(notes_dir) if e.get("version") != new_entry["version"]]
    entries.append(new_entry)
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    atomic_write(notes_dir / "changelog-index.json", json.dumps({"releases": entries}, indent=2) + "\n")


def cmd_set(target: str, new_str: str, message: str, dry_run: bool, force: bool = False) -> None:
    cfg = TARGETS[target]
    pkg, notes_dir = cfg["package"], cfg["notes_dir"]
    if not SEMVER_RE.match(new_str):
        sys.exit(f"ERROR: {new_str!r} is not X.Y.Z semver")
    old = read_version(pkg)
    new = tuple(int(x) for x in new_str.split("."))
    if new <= old and not force:
        sys.exit(
            f"ERROR: {target} version {new_str} must be greater than current "
            f"{old[0]}.{old[1]}.{old[2]} (use --force to override)"
        )
    notes_file = notes_dir / f"{new_str}.txt"

    if notes_file.exists():
        sys.exit(f"ERROR: release notes for {target} {new_str} already exist at {notes_file}")

    print(f"{target}: {new_str}  (set)")
    print(f"  {pkg}: {old[0]}.{old[1]}.{old[2]} -> {new_str}")
    print(f"  {notes_file}: {message!r}")
    print(f"  {notes_dir / 'changelog-index.json'}: updated")

    if dry_run:
        print("(dry run - nothing written)")
        return

    entry = {"version": new_str, "date": date.today().isoformat(), "file": f"{new_str}.txt"}
    atomic_write(notes_file, message + "\n")
    rebuild_index(notes_dir, entry)

    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["version"] = new_str
    atomic_write(pkg, json.dumps(data, indent=2) + "\n")
    print(f"OK: {target} set to {new_str}")


def cmd_bump(target: str, component: str, message: str, dry_run: bool) -> None:
    old = read_version(TARGETS[target]["package"])
    new_str = ".".join(map(str, bump_version(old, component)))
    cmd_set(target, new_str, message, dry_run)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bump")
    b.add_argument("target", choices=["ui", "backend", "desktop"], type=str.lower)
    b.add_argument("component", choices=["major", "minor", "patch"])
    b.add_argument("message", nargs="+")
    b.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("set")
    s.add_argument("target", choices=["ui", "backend", "desktop"], type=str.lower)
    s.add_argument("version")
    s.add_argument("message", nargs="+")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true",
                   help="allow setting a version lower than or equal to the current one")

    args = p.parse_args()
    message = " ".join(args.message)
    if args.cmd == "bump":
        cmd_bump(args.target, args.component, message, args.dry_run)
    else:
        cmd_set(args.target, args.version, message, args.dry_run, args.force)


if __name__ == "__main__":
    main()
