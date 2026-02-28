"""Orchestrator for all tool tests."""
from __future__ import annotations

import json
import os
import sys

# Ensure repo root is on sys.path so `src.*` imports work.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tool_tests.helpers.env import make_env
from tool_tests.helpers.http_server import MicroServer, start_server, stop_server
from tool_tests.helpers.result import TestResult

# ---------------------------------------------------------------------------
# Colour helpers (termcolor is optional; fall back to plain text if absent)
# ---------------------------------------------------------------------------
try:
    from termcolor import colored

    def _c(text: str, *args, **kwargs) -> str:
        return colored(str(text), *args, **kwargs)

except ImportError:
    def _c(text: str, color=None, on_color=None, attrs=None, **kwargs) -> str:
        return str(text)


def _bold(text: str) -> str:
    return _c(text, attrs=["bold"])


# ---------------------------------------------------------------------------
# Lazy imports of test modules — done at run time to avoid import errors
# stopping all tests when one module fails to import.
# ---------------------------------------------------------------------------

_TEST_MODULES = [
    # Session memory tools
    "tool_tests.individual.test_session_memory_set_variable",
    "tool_tests.individual.test_session_memory_get_variable",
    "tool_tests.individual.test_session_memory_list_variables",
    "tool_tests.individual.test_session_memory_delete_variable",
    "tool_tests.individual.test_session_memory_append_to_variable",
    "tool_tests.individual.test_session_memory_concat",
    "tool_tests.individual.test_session_memory_copy_rename",
    "tool_tests.individual.test_session_memory_count_chars",
    "tool_tests.individual.test_session_memory_count_lines",
    "tool_tests.individual.test_session_memory_read_lines",
    "tool_tests.individual.test_session_memory_read_char_range",
    "tool_tests.individual.test_session_memory_insert_lines",
    "tool_tests.individual.test_session_memory_delete_lines",
    "tool_tests.individual.test_session_memory_replace_lines",
    "tool_tests.individual.test_session_memory_apply_patch",
    "tool_tests.individual.test_session_memory_check_eol",
    "tool_tests.individual.test_session_memory_normalize_eol",
    "tool_tests.individual.test_session_memory_check_indentation",
    "tool_tests.individual.test_session_memory_convert_indentation",
    "tool_tests.individual.test_session_memory_search_by_regex",
    "tool_tests.individual.test_session_memory_extract_json_value",
    # Filesystem tools
    "tool_tests.individual.test_get_pwd",
    "tool_tests.individual.test_change_pwd",
    "tool_tests.individual.test_list_dir",
    "tool_tests.individual.test_list_working_tree",
    "tool_tests.individual.test_create_dir",
    "tool_tests.individual.test_create_text_file",
    "tool_tests.individual.test_delete_file",
    "tool_tests.individual.test_remove_dir",
    "tool_tests.individual.test_read_text_file_to_session_memory",
    "tool_tests.individual.test_write_text_file_from_session_memory",
    "tool_tests.individual.test_search_filesystem_by_regex",
    # Network tools
    "tool_tests.individual.test_basic_web_request",
    "tool_tests.individual.test_brave_web_search",
    # Project memory tools
    "tool_tests.individual.test_project_memory_set_variable",
    "tool_tests.individual.test_project_memory_get_variable",
    "tool_tests.individual.test_project_memory_list_variables",
    "tool_tests.individual.test_project_memory_delete_variable",
    "tool_tests.individual.test_project_memory_search_by_regex",
    # Other tools
    "tool_tests.individual.test_code_interpreter",
    "tool_tests.individual.test_report_impossible",
    "tool_tests.individual.test_todo_list",
    "tool_tests.individual.test_load_skill_files_from_url_to_session_memory",
]


def _tool_name_from_module(module_path: str) -> str:
    """Extract tool name from module path like 'tool_tests.individual.test_foo' -> 'foo'."""
    stem = module_path.rsplit(".", 1)[-1]
    if stem.startswith("test_"):
        return stem[5:]
    return stem


# Apply test exclusions declared in src/tools/_exclude_builtin_tools.py.
try:
    from src.tools._exclude_builtin_tools import EXCLUDE as _test_exclusions
except ImportError:
    _test_exclusions = {}

_testing_excluded: set[str] = {
    name for name, flags in _test_exclusions.items()
    if flags.get("testing") is True
}

if _testing_excluded:
    _TEST_MODULES = [
        m for m in _TEST_MODULES
        if _tool_name_from_module(m) not in _testing_excluded
    ]


def _print_result(result: TestResult) -> None:
    tool = result.tool_name
    print(f"\n  {_bold(_c(tool, 'white'))}")

    if result.error:
        print(f"  {_bold(_c('ERROR', 'red'))} — {_c(result.error, 'red')}")
        if result.traceback:
            for line in result.traceback.splitlines():
                print(f"    {_c(line, 'yellow')}")
        return

    if result.gracefully_skipped:
        badge = _bold(_c("SKIP", "yellow"))
        reasons = [s.description for s in result.sub_tests if result._is_skip(s)]
        reason_str = reasons[0] if reasons else ""
        print(f"  {badge} — {_c(reason_str, 'dark_grey')}")
        return

    badge = _bold(_c("PASS", "green")) if result.success else _bold(_c("FAIL", "red"))
    print(f"  {badge} ({result.checks_passed}/{result.checks_run})")

    for sub in result.sub_tests:
        num_name = f"{sub.number}. {sub.name}"
        if sub.passed:
            print(f"\n    {_c(num_name, 'green')}")
        else:
            print(f"\n    {_c(num_name, 'red')}")
        print(f"       {_c(sub.description, 'dark_grey')}")
        if not sub.passed and sub.detail:
            print(f"       {_c('  detail: ' + sub.detail, 'yellow')}")


def _write_report(results: list[TestResult], results_dir: str) -> None:
    """Write test_results/results.json and copy tool_tests/index.html."""
    import datetime
    import shutil

    os.makedirs(results_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "timestamp": timestamp,
        "total": len(results),
        "passed": sum(1 for r in results if r.success and not r.gracefully_skipped),
        "failed": sum(1 for r in results if not r.success and not r.gracefully_skipped),
        "skipped": sum(1 for r in results if r.gracefully_skipped),
        "results": [r.to_dict() for r in results],
    }

    json_path = os.path.join(results_dir, "results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    src_html = os.path.join(os.path.dirname(__file__), "index.html")
    shutil.copy2(src_html, os.path.join(results_dir, "index.html"))


def main() -> int:
    log_dir = os.path.join(os.path.dirname(__file__), "log")
    results_dir = os.path.join(_REPO_ROOT, "test_results")
    os.makedirs(log_dir, exist_ok=True)

    print(f"\n{_bold('Starting tool tests...')}")

    # Start micro HTTP server
    server: MicroServer | None = None
    try:
        server = start_server()
        print(f"{_c('  HTTP test server started', 'cyan')} on {server.base_url}")
    except Exception as e:
        print(f"{_c('  WARNING: Could not start HTTP test server:', 'yellow')} {e}")
        server = None

    results: list[TestResult] = []
    failed_tools: list[str] = []
    skipped_tools: list[str] = []

    import importlib

    for module_path in _TEST_MODULES:
        tool_name = _tool_name_from_module(module_path)
        env = make_env(tool_name[:20])  # truncate to keep Redis key manageable

        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            from tool_tests.helpers.result import TestResult as TR
            r = TR(tool_name=tool_name, error=f"ImportError: {e}")
            results.append(r)
            _print_result(r)
            failed_tools.append(tool_name)
            env.cleanup()
            continue

        result = None
        try:
            result = mod.run(env, server=server)
        except Exception as e:
            import traceback as _tb
            from tool_tests.helpers.result import TestResult as TR
            result = TR(
                tool_name=tool_name,
                error=f"{type(e).__name__}: {e}",
                traceback=_tb.format_exc(),
            )
        finally:
            env.cleanup()

        results.append(result)
        _print_result(result)

        if result.gracefully_skipped:
            skipped_tools.append(result.tool_name)
        elif not result.success:
            failed_tools.append(result.tool_name)
            log_path = os.path.join(log_dir, f"{result.tool_name}.json")
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(result.to_dict(), f, indent=2)
            except Exception as e:
                print(f"    {_c('WARNING: could not write log: ' + str(e), 'yellow')}")

    # Stop server
    if server is not None:
        try:
            stop_server(server)
        except Exception:
            pass

    # Write static report
    try:
        _write_report(results, results_dir)
        print(f"\n  {_c('Report written to', 'cyan')} {_c('test_results/', 'white')}  "
              f"{_c('(run ./tool_tests/view.sh to open)', 'dark_grey')}")
    except Exception as e:
        print(f"  {_c('WARNING: could not write report: ' + str(e), 'yellow')}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r.success and not r.gracefully_skipped)
    failed = len(failed_tools)
    skipped = len(skipped_tools)

    print(f"\n\n{_bold('== Summary ==')}")
    print(
        f"  Passed:  {_c(str(passed), 'green')}/{total}   "
        f"Failed: {_c(str(failed), 'red' if failed else 'green')}   "
        f"Skipped: {_c(str(skipped), 'yellow' if skipped else 'green')}"
    )

    if failed_tools:
        print(f"  Failures: {_c(', '.join(failed_tools), 'red')}")

    if skipped_tools:
        print(f"  Graceful skips: {_c(', '.join(skipped_tools), 'yellow')}")
        print(f"  {_c('(skips may indicate missing mocking — consider adding stubs)', 'dark_grey')}")

    return 1 if failed_tools else 0


if __name__ == "__main__":
    sys.exit(main())
