"""
Aggregate runner: imports and runs all list_dir test modules.
Exit code 0 = all pass, 1 = at least one failure.
"""
from __future__ import annotations

import sys
import os

# Ensure repo root is on sys.path (python_in_env.sh sets PYTHONPATH, but
# running this file directly also works if the repo root is on sys.path).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import tests.list_dir.test_basic as test_basic
import tests.list_dir.test_gitignore as test_gitignore
import tests.list_dir.test_format as test_format

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def main():
    all_failures: list[str] = []

    print()
    failures = test_basic.run()
    all_failures.extend(f"[test_basic] {f}" for f in failures)

    print()
    failures = test_gitignore.run()
    all_failures.extend(f"[test_gitignore] {f}" for f in failures)

    print()
    failures = test_format.run()
    all_failures.extend(f"[test_format] {f}" for f in failures)

    print()
    print("=" * 60)
    if all_failures:
        print(f"{FAIL}  {len(all_failures)} test(s) FAILED:")
        for f in all_failures:
            print(f"    - {f}")
        sys.exit(1)
    else:
        print(f"{PASS}  All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
