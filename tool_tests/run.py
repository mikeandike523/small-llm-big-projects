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
from tool_tests.helpers.result import CheckList, TestResult

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
# Test discovery
# ---------------------------------------------------------------------------


def _discover_tests() -> list[dict]:
    """
    Scan tool_tests/individual/ and return test entries sorted by tool_name.

    Each entry is one of:
      {"type": "file", "tool_name": str, "module_path": str}
      {"type": "dir",  "tool_name": str, "checks_modules": list[str]}

    If both test_<name>.py and <name>/ exist, the file takes precedence.
    """
    individual_dir = os.path.join(os.path.dirname(__file__), "individual")
    entries: list[dict] = []
    all_names = sorted(os.listdir(individual_dir))

    # Collect explicit test_*.py files first so we know which names are covered.
    file_tool_names: set[str] = set()
    for name in all_names:
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        if not os.path.isfile(os.path.join(individual_dir, name)):
            continue
        tool_name = name[5:-3]  # strip "test_" and ".py"
        file_tool_names.add(tool_name)
        entries.append(
            {
                "type": "file",
                "tool_name": tool_name,
                "module_path": f"tool_tests.individual.{name[:-3]}",
            }
        )

    # Collect directories containing checks_*.py files.
    for name in all_names:
        if name.startswith(("_", ".")):
            continue
        if not os.path.isdir(os.path.join(individual_dir, name)):
            continue
        if name in file_tool_names:
            continue  # explicit test file takes precedence
        checks_files = sorted(
            f
            for f in os.listdir(os.path.join(individual_dir, name))
            if f.startswith("checks_") and f.endswith(".py")
        )
        if not checks_files:
            continue
        entries.append(
            {
                "type": "dir",
                "tool_name": name,
                "checks_modules": [
                    f"tool_tests.individual.{name}.{f[:-3]}" for f in checks_files
                ],
            }
        )

    entries.sort(key=lambda e: e["tool_name"])
    return entries


# Apply test exclusions declared in src/tools/_exclude_builtin_tools.py.
try:
    from src.tools._exclude_builtin_tools import EXCLUDE as _test_exclusions
except ImportError:
    _test_exclusions = {}

_testing_excluded: set[str] = {
    name for name, flags in _test_exclusions.items() if flags.get("testing") is True
}


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
    import importlib

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

    test_entries = _discover_tests()
    if _testing_excluded:
        test_entries = [
            e for e in test_entries if e["tool_name"] not in _testing_excluded
        ]

    results: list[TestResult] = []
    failed_tools: list[str] = []
    skipped_tools: list[str] = []

    for entry in test_entries:
        tool_name = entry["tool_name"]
        env = make_env(tool_name[:20])
        result: TestResult | None = None

        try:
            if entry["type"] == "file":
                try:
                    mod = importlib.import_module(entry["module_path"])
                except ImportError as e:
                    result = TestResult(tool_name=tool_name, error=f"ImportError: {e}")
                else:
                    try:
                        result = mod.run(env, server=server)
                    except Exception as e:
                        import traceback as _tb

                        result = TestResult(
                            tool_name=tool_name,
                            error=f"{type(e).__name__}: {e}",
                            traceback=_tb.format_exc(),
                        )

            else:  # "dir" — fuse all checks_*.py modules into one CheckList
                cl = CheckList(tool_name)
                try:
                    for mod_path in entry["checks_modules"]:
                        mod = importlib.import_module(mod_path)
                        mod.add_checks(cl, env)
                except Exception as e:
                    cl.record_exception(e)
                result = cl.result()

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
        print(
            f"\n  {_c('Report written to', 'cyan')} {_c('test_results/', 'white')}  "
            f"{_c('(run ./tool_tests/view.sh to open)', 'dark_grey')}"
        )
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
        print(
            f"  {_c('(skips may indicate missing mocking — consider adding stubs)', 'dark_grey')}"
        )

    return 1 if failed_tools else 0


if __name__ == "__main__":
    sys.exit(main())
