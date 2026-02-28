from __future__ import annotations
import subprocess
from dataclasses import dataclass

@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    success: bool

def run_command(cmd: list[str], timeout: int | None = None) -> SubprocessResult:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return SubprocessResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        success=result.returncode == 0,
    )
