"""Test runner for execute_tool dispatch tests."""
from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.execute_tool_dispatch import test_basic


def main() -> None:
    all_failures: list[str] = []
    all_failures.extend(test_basic.run())

    print()
    if all_failures:
        print(f"{len(all_failures)} test(s) FAILED:")
        for f in all_failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All execute_tool dispatch tests passed.")


if __name__ == "__main__":
    main()
