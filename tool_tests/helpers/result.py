from __future__ import annotations

import traceback as _traceback
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SubTestResult:
    number: int
    name: str
    description: str
    passed: bool
    detail: str = ""
    skipped: bool = False  # explicitly marked via CheckList.skip()


@dataclass
class TestResult:
    tool_name: str
    sub_tests: list[SubTestResult] = field(default_factory=list)
    error: Optional[str] = None
    traceback: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and all(s.passed for s in self.sub_tests)

    @property
    def checks_run(self) -> int:
        return len(self.sub_tests)

    @property
    def checks_passed(self) -> int:
        return sum(1 for s in self.sub_tests if s.passed)

    @staticmethod
    def _is_skip(s: SubTestResult) -> bool:
        """Detect explicit skips and legacy skip-pattern checks."""
        if s.skipped:
            return True
        # Legacy pattern: check name or description contains "skip" and the check passed
        return (
            ("skip" in s.name.lower() or "skip" in s.description.lower())
            and s.passed
        )

    @property
    def checks_skipped(self) -> int:
        return sum(1 for s in self.sub_tests if self._is_skip(s))

    @property
    def gracefully_skipped(self) -> bool:
        """True when the test succeeded but every check was a graceful skip marker
        (i.e. no real assertions were exercised)."""
        if not self.success or not self.sub_tests:
            return False
        return all(self._is_skip(s) for s in self.sub_tests)

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "gracefully_skipped": self.gracefully_skipped,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_skipped": self.checks_skipped,
            "error": self.error,
            "traceback": self.traceback,
            "sub_tests": [
                {
                    "number": s.number,
                    "name": s.name,
                    "description": s.description,
                    "passed": s.passed,
                    "detail": s.detail,
                    "skipped": self._is_skip(s),
                }
                for s in self.sub_tests
            ],
        }


class CheckList:
    """Accumulates named sub-test results for a single tool test."""

    def __init__(self, tool_name: str) -> None:
        self._tool_name = tool_name
        self._sub_tests: list[SubTestResult] = []
        self._error: Optional[str] = None
        self._traceback: Optional[str] = None

    def check(
        self,
        name: str,
        description: str,
        condition: bool,
        detail: str = "",
    ) -> None:
        number = len(self._sub_tests) + 1
        self._sub_tests.append(
            SubTestResult(
                number=number,
                name=name,
                description=description,
                passed=bool(condition),
                detail=detail if not condition else "",
            )
        )

    def skip(self, reason: str) -> None:
        """Record a graceful skip — use when the test cannot run (missing credentials,
        external service unavailable, etc.) and real assertions are intentionally omitted."""
        number = len(self._sub_tests) + 1
        self._sub_tests.append(
            SubTestResult(
                number=number,
                name="graceful skip",
                description=reason,
                passed=True,
                detail="",
                skipped=True,
            )
        )

    def record_exception(self, exc: BaseException) -> None:
        self._error = f"{type(exc).__name__}: {exc}"
        self._traceback = _traceback.format_exc()

    def result(self) -> TestResult:
        return TestResult(
            tool_name=self._tool_name,
            sub_tests=list(self._sub_tests),
            error=self._error,
            traceback=self._traceback,
        )
