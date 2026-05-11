#!/usr/bin/env python3
"""
AST-based fidelity check: socket_handler_components vs original socket_handlers.py.

Extracts every top-level function from the pre-refactor socket_handlers.py (via
`git show HEAD:...`) and from each component file, then diffs them pair-by-pair.

Output:
  scratchpad/check_extraction/socket_handlers_orig.py  -- the restored original
  scratchpad/check_extraction/report.txt               -- full text report
  scratchpad/check_extraction/diff_<name>.txt          -- one file per differing function

Usage:
  python code-analysis/check_extraction.py [project_root]
"""
import ast
import difflib
import io
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output so unicode chars in diffs (e.g. ellipsis) don't crash on Windows cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_top_level_functions(src: str) -> dict[str, str]:
    """Return {func_name: source_segment} for all top-level function defs."""
    tree = ast.parse(src)
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node)
            if seg:
                result[node.name] = seg
    return result


def unified_diff(a: str, b: str, from_label: str, to_label: str, context: int = 2) -> str:
    return "\n".join(difflib.unified_diff(
        a.splitlines(),
        b.splitlines(),
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
        n=context,
    ))


def header(text: str) -> str:
    bar = "=" * 70
    return f"\n{bar}\n{text}\n{bar}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    scratchpad = project_root / "scratchpad" / "check_extraction"
    scratchpad.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Retrieve original socket_handlers.py from git HEAD
    # ------------------------------------------------------------------
    orig_git_path = "src/ui_connector/socket_handlers.py"
    orig_local = scratchpad / "socket_handlers_orig.py"

    proc = subprocess.run(
        ["git", "show", f"HEAD:{orig_git_path}"],
        capture_output=True,
        text=True,
        cwd=project_root,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        sys.exit(f"git show failed:\n{proc.stderr}")

    orig_src = proc.stdout
    orig_local.write_text(orig_src, encoding="utf-8")
    print(f"Original saved to: {orig_local}")

    # ------------------------------------------------------------------
    # 2. Parse original
    # ------------------------------------------------------------------
    orig_funcs = get_top_level_functions(orig_src)
    print(f"\nOriginal top-level functions ({len(orig_funcs)}):")
    for name in sorted(orig_funcs):
        lines = orig_funcs[name].count("\n") + 1
        print(f"  {name:50s}  ({lines} lines)")

    # ------------------------------------------------------------------
    # 3. Parse every component file
    # ------------------------------------------------------------------
    comp_dir = project_root / "src" / "ui_connector" / "socket_handler_components"
    comp_files = sorted(p for p in comp_dir.glob("*.py") if p.name != "__init__.py")

    # Maps func_name -> (filename, source_segment)
    comp_funcs: dict[str, tuple[str, str]] = {}
    # Maps filename -> list of func names found there
    file_func_index: dict[str, list[str]] = {}

    for cf in comp_files:
        src = cf.read_text(encoding="utf-8")
        funcs = get_top_level_functions(src)
        file_func_index[cf.name] = list(funcs)
        for name, seg in funcs.items():
            comp_funcs[name] = (cf.name, seg)

    print(f"\nComponent functions ({len(comp_funcs)}) by file:")
    for cf in comp_files:
        names = file_func_index.get(cf.name, [])
        print(f"\n  {cf.name}  ({len(names)} functions)")
        for n in names:
            print(f"    {n}")

    # ------------------------------------------------------------------
    # 4. Classify and diff
    # ------------------------------------------------------------------
    ok: list[str] = []
    diffs: list[tuple[str, str, str]] = []   # (name, comp_file, diff_text)
    new_funcs: list[tuple[str, str]] = []    # (name, comp_file)  — not in original
    missing: list[str] = []                  # in original, not in any component

    for name, (comp_file, comp_src) in sorted(comp_funcs.items()):
        if name not in orig_funcs:
            new_funcs.append((name, comp_file))
            continue
        orig_fn = orig_funcs[name]
        if orig_fn.rstrip() == comp_src.rstrip():
            ok.append(name)
        else:
            diff_text = unified_diff(
                orig_fn,
                comp_src,
                from_label=f"original:socket_handlers.py::{name}",
                to_label=f"{comp_file}::{name}",
            )
            diffs.append((name, comp_file, diff_text))
            (scratchpad / f"diff_{name}.txt").write_text(diff_text, encoding="utf-8")

    missing = sorted(set(orig_funcs) - set(comp_funcs))

    # ------------------------------------------------------------------
    # 5. Build and print report
    # ------------------------------------------------------------------
    lines: list[str] = []

    lines.append(header("IDENTICAL FUNCTIONS"))
    for name in ok:
        lines.append(f"  [OK]  {name}")

    lines.append(header("FUNCTIONS WITH DIFFS  (expected: import/state path changes)"))
    for name, comp_file, diff_text in diffs:
        lines.append(f"\n  [DIFF]  {name}  ({comp_file})")
        for dl in diff_text.splitlines():
            lines.append("    " + dl)
        lines.append(f"    -> saved to: scratchpad/check_extraction/diff_{name}.txt")

    lines.append(header("NEW FUNCTIONS  (added in components, not in original)"))
    for name, comp_file in new_funcs:
        lines.append(f"  [NEW]  {name:50s}  ({comp_file})")

    lines.append(header("MISSING FROM COMPONENTS  (in original but not extracted)"))
    for name in missing:
        lines.append(f"  [MISS] {name}")

    lines.append(header("SUMMARY"))
    lines.append(f"  Identical : {len(ok)}")
    lines.append(f"  Differ    : {len(diffs)}")
    lines.append(f"  New       : {len(new_funcs)}")
    lines.append(f"  Missing   : {len(missing)}")

    report = "\n".join(lines)
    print(report)

    report_path = scratchpad / "report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nFull report written to: {report_path}")


if __name__ == "__main__":
    main()
