from __future__ import annotations
import subprocess
from dataclasses import dataclass

@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    success: bool

    def __str__(self):
        parts = [
            "SUCCESS" if self.success else "ERROR",
            f"EXIT CODE: {self.returncode}" if not self.success else None,
            "STDOUT:\n\n"+self.stdout if self.stdout else None,
            "STDERR:\n\n"+self.stderr if self.stderr else None
              ]
        return "\n\n".join(filter(lambda x: (x or '').strip(), parts)).strip()

def run_command(cmd: list[str], timeout: int | None = None) -> SubprocessResult:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return SubprocessResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        success=result.returncode == 0,
    )
