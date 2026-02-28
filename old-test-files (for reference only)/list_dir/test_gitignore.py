"""
Tests for list_dir gitignore parsing: basic ignore rules, directory ignore,
nested .gitignore files.
"""
from __future__ import annotations

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
    from src.tools.list_dir import execute
    return execute(kwargs, {})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gitignore_off_shows_all():
    """With use_gitignore=False (default), all files including .log are shown."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True)

    check("app.log" in result, "gitignore_off: app.log visible", result[:300])
    check("nested.log" in result, "gitignore_off: nested.log visible", result[:300])
    check("test.tmp" in result, "gitignore_off: test.tmp visible", result[:300])
    check("ignored_dir" in result, "gitignore_off: ignored_dir visible", result[:300])
    check("something.txt" in result, "gitignore_off: something.txt visible (in ignored_dir)", result[:300])


def test_gitignore_on_hides_log_files():
    """use_gitignore=True: *.log pattern in root .gitignore hides .log files."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, use_gitignore=True)

    check("app.log" not in result, "gitignore_on: app.log hidden", result)
    check("nested.log" not in result, "gitignore_on: nested.log hidden", result)

    # Non-ignored files should still appear
    check("file1.txt" in result, "gitignore_on: file1.txt still visible", result[:300])
    check("file2.py" in result, "gitignore_on: file2.py still visible", result[:300])
    check("nested.txt" in result, "gitignore_on: nested.txt still visible", result[:300])


def test_gitignore_on_hides_ignored_dir():
    """use_gitignore=True: 'ignored_dir/' pattern hides the entire directory."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, use_gitignore=True)

    check("ignored_dir" not in result, "gitignore_on: ignored_dir hidden", result)
    check("something.txt" not in result, "gitignore_on: something.txt (in ignored_dir) hidden", result)


def test_gitignore_on_nested_gitignore():
    """use_gitignore=True: nested .gitignore in subdir hides *.tmp within subdir."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, use_gitignore=True)

    check("test.tmp" not in result, "gitignore_nested: test.tmp hidden by subdir .gitignore", result)

    # But deep/very_deep.txt should still appear
    check("very_deep.txt" in result, "gitignore_nested: very_deep.txt still visible", result[:300])


def test_gitignore_on_filter_files():
    """use_gitignore=True combined with filter='files' only shows non-ignored files."""
    result = call_list_dir(
        path=FIXTURE_ROOT, recursive=True, filter="files", use_gitignore=True
    )
    lines = set(result.splitlines())

    check("app.log" not in result, "gitignore+filter=files: app.log hidden", result)
    check("nested.log" not in result, "gitignore+filter=files: nested.log hidden", result)
    check("test.tmp" not in result, "gitignore+filter=files: test.tmp hidden", result)
    check("ignored_dir" not in result, "gitignore+filter=files: ignored_dir hidden", result)

    check(any("file1.txt" in l for l in lines), "gitignore+filter=files: file1.txt visible", str(lines))
    check(any("nested.txt" in l for l in lines), "gitignore+filter=files: nested.txt visible", str(lines))


def test_gitignore_on_non_recursive():
    """use_gitignore=True with non-recursive listing still hides top-level entries."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=False, use_gitignore=True)

    check("app.log" not in result, "gitignore_nonrec: app.log hidden at top level", result)
    check("ignored_dir" not in result, "gitignore_nonrec: ignored_dir hidden at top level", result)
    check("file1.txt" in result, "gitignore_nonrec: file1.txt visible", result)
    check("subdir" in result, "gitignore_nonrec: subdir visible", result)


def test_gitignore_gitignore_file_itself_visible():
    """.gitignore file itself is NOT in any ignore rules, so it appears."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=False, use_gitignore=True)
    # The .gitignore file should still appear (it's not self-ignoring)
    check(".gitignore" in result, "gitignore_file_visible: .gitignore itself visible", result)


def test_gitignore_on_json_format():
    """use_gitignore=True with format='json' also excludes ignored entries."""
    import json as json_mod
    result = call_list_dir(
        path=FIXTURE_ROOT, recursive=True, format="json", use_gitignore=True
    )
    data = json_mod.loads(result)

    def collect_names(node):
        """Recursively collect all names from the JSON tree."""
        names = set()
        if isinstance(node, dict):
            names.add(node.get("name", node.get("path", "")))
            for child in node.get("children", []):
                names |= collect_names(child)
        elif isinstance(node, list):
            for item in node:
                names |= collect_names(item)
        return names

    names = collect_names(data)
    check("app.log" not in names, "gitignore+json: app.log absent", str(names))
    check("ignored_dir" not in names, "gitignore+json: ignored_dir absent", str(names))
    check("file1.txt" in names, "gitignore+json: file1.txt present", str(names))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run():
    print("=== test_gitignore.py ===")
    test_gitignore_off_shows_all()
    test_gitignore_on_hides_log_files()
    test_gitignore_on_hides_ignored_dir()
    test_gitignore_on_nested_gitignore()
    test_gitignore_on_filter_files()
    test_gitignore_on_non_recursive()
    test_gitignore_gitignore_file_itself_visible()
    test_gitignore_on_json_format()
    return _failures


if __name__ == "__main__":
    failures = run()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
