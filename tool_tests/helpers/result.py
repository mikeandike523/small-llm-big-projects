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

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "error": self.error,
            "traceback": self.traceback,
            "sub_tests": [
                {
                    "number": s.number,
                    "name": s.name,
                    "description": s.description,
                    "passed": s.passed,
                    "detail": s.detail,
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
