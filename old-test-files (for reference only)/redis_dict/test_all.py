"""
Test runner for all RedisDict tests.
"""
from __future__ import annotations

import sys
import os

# Ensure the project root is on sys.path so src.* imports resolve.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.redis_dict import test_basic


def main() -> None:
    all_failures: list[str] = []

    failures = test_basic.run()
    all_failures.extend(failures)

    print()
    if all_failures:
        print(f"{len(all_failures)} test(s) FAILED across all suites:")
        for f in all_failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All RedisDict tests passed.")


if __name__ == "__main__":
    main()
