"""
Basic tests for list_dir: non-recursive, recursive, depth limits, filter modes.
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures: list[str] = []


def check(condition: bool, test_name: str, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {test_name}")
    else:
        msg = f"  {FAIL}  {test_name}"
        if detail:
            msg += f"\n       detail: {detail}"
        print(msg)
        _failures.append(test_name)


def get_failures() -> list[str]:
    return _failures


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_ROOT = os.path.join(REPO_ROOT, "scratchpad", "list_dir_test", "root")


def call_list_dir(**kwargs):
    """Call list_dir.execute with a fresh session_data dict."""
    from src.tools.list_dir import execute
    return execute(kwargs, {})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_non_recursive_text():
    """Non-recursive listing produces root + immediate children in tree form."""
    result = call_list_dir(path=FIXTURE_ROOT)
    lines = result.splitlines()

    # First line should be the root directory name
    check(lines[0] == "root/", "non-recursive: first line is 'root/'", repr(lines[0]))

    # Should see immediate children (files and subdirs) — all at 2-space indent
    indented = [l for l in lines[1:] if l.startswith("  ") and not l.startswith("    ")]
    names = {l.strip().rstrip("/") for l in indented}

    check(".gitignore" in names, "non-recursive: .gitignore present", str(names))
    check("file1.txt" in names, "non-recursive: file1.txt present", str(names))
    check("file2.py" in names, "non-recursive: file2.py present", str(names))
    check("app.log" in names, "non-recursive: app.log present (gitignore off)", str(names))
    check("subdir" in names, "non-recursive: subdir present", str(names))
    check("ignored_dir" in names, "non-recursive: ignored_dir present (gitignore off)", str(names))
    check("empty_dir" in names, "non-recursive: empty_dir present", str(names))

    # Grandchildren should NOT appear (no recursion)
    all_lines_text = "\n".join(lines)
    check("nested.txt" not in all_lines_text, "non-recursive: no grandchildren", all_lines_text)


def test_recursive_text():
    """Recursive listing shows all descendants."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True)
    lines = result.splitlines()

    check("nested.txt" in result, "recursive: nested.txt present", result[:200])
    check("very_deep.txt" in result, "recursive: very_deep.txt present", result[:200])

    # subdir should appear as a folder entry
    check(any("subdir/" in l for l in lines), "recursive: subdir/ shown as folder", str(lines[:10]))

    # deep/ should appear nested under subdir/
    check(any("deep/" in l for l in lines), "recursive: deep/ folder shown", str(lines))


def test_depth_zero():
    """depth=0 lists immediate children only — same as non-recursive."""
    result_depth0 = call_list_dir(path=FIXTURE_ROOT, recursive=True, depth=0)
    result_nonrec = call_list_dir(path=FIXTURE_ROOT, recursive=False)
    check(result_depth0 == result_nonrec, "depth=0 equals non-recursive output",
          f"depth0:\n{result_depth0}\n\nnonrec:\n{result_nonrec}")


def test_depth_one():
    """depth=1 shows root's children and their immediate children."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, depth=1)

    # nested.txt is in subdir/ — should appear
    check("nested.txt" in result, "depth=1: nested.txt visible", result)

    # very_deep.txt is in subdir/deep/ — should NOT appear
    check("very_deep.txt" not in result, "depth=1: very_deep.txt NOT visible", result)


def test_filter_files_text():
    """filter='files' produces flat list of files (no directories)."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files")
    lines = [l for l in result.splitlines() if l.strip()]

    # Should be flat paths — no trailing slashes
    for line in lines:
        check(not line.strip().endswith("/"), f"filter=files no trailing slash: {line!r}", line)

    # Should see files like file1.txt, subdir/nested.txt
    paths = set(lines)
    check(any("file1.txt" in p for p in paths), "filter=files: file1.txt present", str(paths))
    check(any("nested.txt" in p for p in paths), "filter=files: subdir/nested.txt present", str(paths))

    # No directory-only entries
    check(not any(p.endswith("/") for p in paths), "filter=files: no dir entries", str(paths))


def test_filter_folders_text():
    """filter='folders' produces flat list of directory paths."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="folders")
    lines = [l for l in result.splitlines() if l.strip()]
    paths = set(lines)

    check(any("subdir" in p for p in paths), "filter=folders: subdir present", str(paths))
    check(any("deep" in p for p in paths), "filter=folders: deep present", str(paths))
    check(any("empty_dir" in p for p in paths), "filter=folders: empty_dir present", str(paths))

    # No file entries should appear
    check(not any("file1.txt" in p for p in paths), "filter=folders: no file1.txt", str(paths))
    check(not any("nested.txt" in p for p in paths), "filter=folders: no nested.txt", str(paths))


def test_show_data_true():
    """show_data=True adds type annotations to entries."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, show_data=True)

    check("(file)" in result, "show_data: (file) annotation present", result[:300])
    check("(folder)" in result, "show_data: (folder) annotation present", result[:300])


def test_show_data_filter_files():
    """show_data=True with filter='files' appends (file) after each path."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files", show_data=True)
    lines = [l for l in result.splitlines() if l.strip()]

    for line in lines:
        check(
            line.endswith("(file)") or "(link" in line,
            f"show_data+filter=files: annotation present on {line!r}",
            line,
        )


def test_session_memory():
    """target='session_memory' writes result to session_data['memory']."""
    session_data: dict = {}
    from src.tools.list_dir import execute
    msg = execute(
        {"path": FIXTURE_ROOT, "target": "session_memory", "memory_key": "test_listing"},
        session_data,
    )
    check("test_listing" in msg, "session_memory: success message mentions key", msg)
    check("memory" in session_data, "session_memory: session_data['memory'] populated", str(session_data))
    check("test_listing" in session_data.get("memory", {}), "session_memory: key present", str(session_data))
    stored = session_data["memory"]["test_listing"]
    check("root/" in stored, "session_memory: stored value looks like listing", stored[:100])


def test_nonexistent_path():
    """list_dir returns an error string for non-existent paths."""
    result = call_list_dir(path="/nonexistent/path/that/does/not/exist/xyz")
    check(result.startswith("Error:"), "nonexistent path: returns Error string", result)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run():
    print("=== test_basic.py ===")
    test_non_recursive_text()
    test_recursive_text()
    test_depth_zero()
    test_depth_one()
    test_filter_files_text()
    test_filter_folders_text()
    test_show_data_true()
    test_show_data_filter_files()
    test_session_memory()
    test_nonexistent_path()
    return _failures


if __name__ == "__main__":
    failures = run()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
