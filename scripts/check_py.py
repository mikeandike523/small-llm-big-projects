#!/usr/bin/env python3
"""
Check that all .py files under src/ compile and that their absolute imports resolve.
Usage: bash python_in_env.sh scripts/check_py.py
"""

import ast
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SRC_DIR = REPO_ROOT / "src"


@dataclass
class IgnoreRule:
    module: str  # top-level package name to suppress (e.g. "ptyprocess")
    reason: str
    platforms: list[str] = field(default_factory=list)  # empty = all platforms


# fmt: off
IGNORE_RULES: list[IgnoreRule] = [
    IgnoreRule(
        module="ptyprocess",
        reason="Unix-only PTY library; not available on Windows",
        platforms=["win32"],
    ),
]
# fmt: on


def _is_ignored(top_level_module: str) -> bool:
    platform = sys.platform
    for rule in IGNORE_RULES:
        if rule.module != top_level_module:
            continue
        if not rule.platforms or platform in rule.platforms:
            return True
    return False


errors: list[str] = []


def check_file(path: Path) -> None:
    rel = path.relative_to(REPO_ROOT)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        errors.append(f"{rel}: SyntaxError at line {e.lineno}: {e.msg}")
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(alias.name, rel)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue  # relative imports are intra-package; skip
            if node.module:
                _check_import(node.module, rel)


def _check_import(module_name: str, src_file: Path) -> None:
    parts = module_name.split(".")

    # Internal imports (src.*): resolve to disk path — find_spec fails on
    # namespace packages (no __init__.py), so we check the file system directly.
    if parts[0] == "src":
        as_file = REPO_ROOT.joinpath(*parts[:-1], parts[-1] + ".py")
        as_pkg = REPO_ROOT.joinpath(*parts, "__init__.py")
        as_ns = REPO_ROOT.joinpath(*parts)  # namespace package (dir, no __init__)
        if not as_file.exists() and not as_pkg.exists() and not as_ns.is_dir():
            errors.append(f"{src_file}: unresolved import '{module_name}'")
        return

    # External packages: checking the top-level is sufficient — sub-module
    # paths within an installed package can't be checked without importing.
    top = parts[0]
    if _is_ignored(top):
        return
    try:
        spec = importlib.util.find_spec(top)
        if spec is None:
            errors.append(
                f"{src_file}: unresolved import '{module_name}' ('{top}' not found)"
            )
    except (ModuleNotFoundError, ValueError):
        errors.append(
            f"{src_file}: unresolved import '{module_name}' ('{top}' not found)"
        )


files = sorted(SRC_DIR.rglob("*.py"))
print(f"Checking {len(files)} files under src/ ...")

for f in files:
    check_file(f)

if errors:
    print(f"\n{len(errors)} error(s):\n")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)

print("All OK.")
